import abc
import hashlib
import warnings
import pathlib
import io
import contextlib
import functools

from typing import ClassVar, Union, Tuple, ContextManager

from gufe.storage.errors import (
    MissingExternalResourceError, ChangedExternalResourceError
)


class _ForceContext:
    """Wrapper that forces objects to only be used a context managers.

    Filelike objects can often be used with explicit open/close. This
    requires the returned filelike to be consumed as a context manager.
    """
    def __init__(self, context):
        self._context = context

    def __enter__(self):
        return self._context.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        return self._context.__exit__(exc_type, exc_value, traceback)


class ExternalStorage(abc.ABC):
    """Abstract base for external storage."""

    allow_changed: ClassVar[bool] = False

    def validate(self, location, metadata):
        if not self.get_metadata(location) == metadata:
            msg = (f"Hash mismatch for {location}: this object "
                   "may have changed.")
            if not self.allow_changed:
                # NOTE: having it here instead of in a DataLoader means that
                # you can only change it for the whole system, instead of
                # for a specific object
                raise ChangedExternalResourceError(
                    msg + " To allow this, set ExternalStorage."
                    "allow_changed = True"
                )
            else:
                warnings.warn(msg)

    def _get_hexdigest(self, location) -> str:
        """Default method for getting the md5 hexdigest.

        Subclasses may implement faster approaches.
        """
        with self._load_stream(location) as filelike:
            hasher = hashlib.md5()
            # TODO: chunking may give better performance
            hasher.update(filelike.read())
            digest = hasher.hexdigest()

        return digest

    def get_metadata(self, location: str) -> str:
        """
        Obtain the metadata associated with the actual stored data.

        We always and only obtain the metadata *after* the data has been
        stored. This is because some potential metadata fields, such as
        last-modified timestamps, may not be known until the data is stored.

        Parameters
        ----------
        location : str
            the label to obtain the metadata about

        Returns
        -------
        str :
            hexdigest of the md5 hash of the data
        """
        # NOTE: in the future, this may become a (named)tuple of metadata.
        # Subclasses would implement private methods to get each field.
        return self._get_hexdigest(location)

    def get_filename(self, location, metadata) -> str:
        # we'd like to not need to include the get_filename method, but for
        # now some consumers of this may not work with filelike
        self.validate(location, metadata)
        return self._get_filename(location)

    # @force_context
    def load_stream(self, location, metadata) -> ContextManager:
        """
        Load data for the given chunk in a context manager.

        This returns a ``_ForceContext``, which requires that the returned
        object be used as a context manager. That ``_ForcedContext`` should
        wrap a filelike objet.

        Subclasses should implement ``_load_stream``.

        Parameters
        ----------
        location : str
            the label for the data to load
        metadata : str
            metadata to validate that the loaded data is still valid

        Returns
        -------
        _ForceContext : ContextManager
            Wrapper around the filelike
        """
        self.validate(location, metadata)
        return _ForceContext(self._load_stream(location))

    def delete(self, location):
        """
        Delete an existing data chunk from the backend.

        Subclasses should implement ``_delete``.

        Parameters
        ----------
        location : str
            label for the data to delete

        Raises
        ------
        MissingExternalResourceError
            If the resource to be deleted does not exist
        """
        return self._delete(location)

    def store(self, location, byte_data) -> Tuple[str, str]:
        """
        Store given data in the backend.

        Subclasses should implement ``_store``.

        Parameters
        ----------
        location : str
            label associated with the data to store
        byte_data : bytes
            bytes to store

        Returns
        -------
        location : str
            the label as input?
        metadata : str
            the resulting metadata from storing this
        """
        return self._store(location, byte_data)

    def exists(self, location) -> bool:
        """
        Check whether a given label has already been used.

        Subclasses should implement ``_exists``.

        Parameters
        ----------
        location : str
            the label to check for

        Return
        ------
        bool
            True if this label has associated data in the backend, False if
            not
        """
        return self._exists(location)

    @abc.abstractmethod
    def _store(self, location, byte_data):
        """
        For implementers: This should be blocking, even if the storage
        backend allows asynchronous storage.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _exists(self, location) -> bool:
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete(self, location):
        raise NotImplementedError()

    @abc.abstractmethod
    def _get_filename(self, location):
        raise NotImplementedError()

    @abc.abstractmethod
    def _load_stream(self, location):
        raise NotImplementedError()


# TODO: this should use pydantic to check init inputs
class FileStorage(ExternalStorage):
    def __init__(self, root_dir: Union[pathlib.Path, str]):
        self.root_dir = pathlib.Path(root_dir)

    def _exists(self, location):
        return self._as_path(location).exists()

    def _store(self, location, byte_data):
        path = self._as_path(location)
        directory = path.parent
        filename = path.name
        # TODO: add some stuff here to catch permissions-based errors
        directory.mkdir(parents=True, exist_ok=True)
        with open(path, mode='wb') as f:
            f.write(byte_data)

        return str(path), self.get_metadata(str(path))

    def _delete(self, location):
        path = self._as_path(location)
        if self.exists(location):
            path.unlink()
        else:
            raise MissingExternalResourceError(
                f"Unable to delete '{str(path)}': File does not exist"
            )

    def _as_path(self, location):
        return self.root_dir / pathlib.Path(location)

    def _get_filename(self, location):
        return str(self._as_path(location))

    def _load_stream(self, location):
        try:
            return open(self._as_path(location), 'rb')
        except OSError as e:
            raise MissingExternalResourceError(str(e))


class MemoryStorage(ExternalStorage):
    """Not for production use, but potentially useful in testing"""
    def __init__(self):
        self._data = {}

    def _exists(self, location):
        return location in self._data

    def _delete(self, location):
        try:
            del self._data[location]
        except KeyError:
            raise MissingExternalResourceError(
                f"Unable to delete '{location}': key does not exist"
            )

    def _store(self, location, byte_data):
        self._data[location] = byte_data
        return location, self.get_metadata(location)

    def _get_filename(self, location):
        # TODO: how to get this to work? how to manage tempfile? maybe a
        # __del__ here?
        pass

    def _load_stream(self, location):
        byte_data = self._data[location]
        stream = io.BytesIO(byte_data)
        return stream
