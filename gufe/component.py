# This code is part of OpenFE and is licensed under the MIT license.
# For details, see https://github.com/OpenFreeEnergy/gufe

import abc
from typing import Union


class Component(abc.ABC):
    """Base class for members of a ChemicalState"""
    @abc.abstractmethod
    def __hash__(self):
        pass

    @abc.abstractmethod
    def __eq__(self, other):
        pass

    @abc.abstractmethod
    def to_dict(self) -> dict:
        pass

    @classmethod
    @abc.abstractmethod
    def from_dict(cls, d: dict):
        pass

    @property
    @abc.abstractmethod
    def total_charge(self) -> Union[int, None]:
        """Net formal charge for the Component if defined"""
        ...
