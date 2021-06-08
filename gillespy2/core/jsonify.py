import re
import copy
import json
import pydoc
import numpy
import hashlib

from json import JSONEncoder


class Jsonify:
    """
    Interface to allow for instances of arbitrary types to be encoded into json strings and decoded into new objects.
    """

    _hash_private_vars = False
    _translation_table = None

    def to_json(self):
        """
        Convert self into a json string.
        """

        encoder = ComplexJsonCoder()
        return json.dumps(copy.deepcopy(self), indent=4, sort_keys=True, default=encoder.default)

    @classmethod
    def from_json(cls, json_object):
        """
        Convert some json_object into a decoded Python type. This function should return a new instance of the type.

        :param json_object: A json str to be converted into a new type instance.
        :param translation_table: A dictionary used to translate anonymous names back into user-defined.
        """

        # If the json_object is actually a dict, it means we've decoded as much as possible.
        if type(json_object) is dict:
            return cls.from_dict(json_object)

        decoder = ComplexJsonCoder()
        return json.loads(json_object, object_hook=decoder.decode)

    def to_dict(self):
        """
        Convert the object into a dictionary ready for json encoding.
        Note: Complex types that inherit from Jsonify do not need to be manually encoded.

        By default, this function will return a dictionary of the object's public types.

        :param self: Instance of the object to convert into a dict.
        """

        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, dict):
        """
        Convert some dict into a new instance of a python type. This function will return a __new__ instance of the tupe.

        :param dict: The dictionary to apply onto the new instance.
        """

        new = cls.__new__(cls)
        new.__dict__ = dict.copy()

        return new

    def to_anon(self):
        """
        Converts self into an anonymous instance of self.
        """

        return self.get_translation_table().obj_to_anon(copy.deepcopy(self))

    def to_named(self):
        """
        Converts self into a named instance of self.
        """
        return self.get_translation_table().obj_to_named(copy.deepcopy(self))

    def get_translation_table(self):
        """
        Make and/or return the translation table.
        """
        if self._translation_table is None:
            self._translation_table = self.make_translation_table()

        return self._translation_table

    def make_translation_table(self):
        """
        Make a translation table that describes key:value pairs to convert user-define data into generic equivalents.
        """
        raise NotImplementedError("make_translation_table() has not been implemented.")

    def public_vars(self):
        """
        Gets a dictionary of public vars that exist on self. Keys starting with '_' are ignored.
        """
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def get_json_hash(self):
        """
        Get the hash of the json representation of self.
        """

        # If _hash_private_vars is set, hash ALL properties on the object.
        if self._hash_private_vars:
            return hashlib.md5(str.encode(self.to_json())).hexdigest()

        # Strip all private variables out of the model.
        model = copy.deepcopy(self)
        model.__dict__ = model.public_vars()

        return hashlib.md5(str.encode(model.to_json())).hexdigest()

    def __eq__(self, o):
        """
        Overload to compare the json of two objects that derive from Jsonify. This method will not do any 
        additional translation.
        """
        return self.get_json_hash() == o.get_json_hash()

class ComplexJsonCoder(JSONEncoder):
    def __init__(self, translation_table=None, **kwargs):
        super(ComplexJsonCoder, self).__init__(**kwargs)
        self._translation_table = translation_table

    def default(self, obj):
        """
        This function is called when json.dumps() fires. default() is a bad name for the function,
        but anything else makes JSONEncoder freak out.

        :param obj: The object that is currently being encoded into JSON.
        """

        from gillespy2.core.model import Model

        # If obj is of matching type, use a custom coder.
        if isinstance(obj, numpy.ndarray):
            return NdArrayCoder.to_dict(obj)

        if isinstance(obj, set):
            return SetCoder.to_dict(obj)

        if isinstance(obj, type):
            return TypeCoder.to_dict(obj)

        if not isinstance(obj, Jsonify):
            return super().default(obj)

        model = obj.to_dict()

        # If the model is some subclass of gillespy2.core.model.Model, then manually set its type.
        if issubclass(obj.__class__, Model):
            model["_type"] = f"{Model.__module__}.{Model.__name__}"

        else:
            model["_type"] = f"{obj.__class__.__module__}.{obj.__class__.__name__}"

        return model

    def decode(self, obj):
        # _type is a field embedded by the encoder to indicate which Jsonify instance will be used to decode the json string.
        if "_type" not in obj:
            return obj

        obj_type = pydoc.locate(obj["_type"])

        if obj_type is None:
            raise Exception(f"{obj_type} does not exist.")

        # If the type is not a subclass of Jsonify, throw an exception. We do this to prevent the execution of arbitrary code.
        if not issubclass(obj_type, Jsonify):
            raise Exception(f"{obj_type}")

        return obj_type.from_json(obj)

class TranslationTable(Jsonify):
    def __init__(self, to_anon):
        self.to_anon = to_anon.copy()
        self.to_named = dict((v, k) for k, v in list(self.to_anon.items()))

    def obj_to_anon(self, obj):
        return self.recursive_translate(obj, self.to_anon)

    def obj_to_named(self, obj):
        return self.recursive_translate(obj, self.to_named)

    def recursive_translate(self, obj, translation_table):
        # If a translation table exists on the object, remove and save it.
        if obj._translation_table is not None:
            saved_table = obj.__dict__.pop("_translation_table")

        translated = self._recursive_translate(obj, translation_table)

        # Restore the original translation table, if needed.
        if saved_table is not None:
            obj._translation_table = saved_table

        return translated

    def _recursive_translate(self, obj, translation_table):
        # The obj is a class if it's an instance of Jsonify. Class property names *cannot*
        # be changed, so translate just the values.
        if isinstance(obj, Jsonify):
            for key in vars(obj).keys():
                vars(obj)[key] = self._recursive_translate(vars(obj)[key], translation_table)

        elif isinstance(obj, list):
            for item in obj:
                item = self._recursive_translate(item, translation_table)

        elif isinstance(obj, dict):
            # Convert the dictionary into a list of tuples. This makes it easier to modify key names.
            obj = list((k, v) for k, v in obj.items())
            new_pairs = [ ]

            for pair in obj:
                new_pairs.append((
                    self._recursive_translate(pair[0], translation_table),
                    self._recursive_translate(pair[1], translation_table)
                ))

            obj = dict((x[0], x[1]) for x in new_pairs)

        # If the obj is a string, translate it via a regex replace. 
        # Note: mathematical functions contain additional characters that should not be translated.
        elif isinstance(obj, str):
            # To handle functions, grab all complete words from the string.
            matches = re.finditer("([0-z])+", obj)

            # For each match, translate the group.
            for match in matches:
                group = match.group()
                obj = obj.replace(group, translation_table.get(group, group))

        return obj

class NdArrayCoder(Jsonify):
    @staticmethod
    def to_dict(self):
        return {
            "data": self.tolist(),
            "_type": f"{NdArrayCoder.__module__}.{NdArrayCoder.__name__}"
        }

    @staticmethod
    def from_json(json_object):
        return numpy.array(json_object["data"])

class SetCoder(Jsonify):
    @staticmethod
    def to_dict(self):
        return {
            "data": list(self),
            "_type": f"{SetCoder.__module__}.{SetCoder.__name__}"
        }

    @staticmethod
    def from_json(json_object):
        return set(json_object["data"])

class TypeCoder(Jsonify):
    @staticmethod
    def to_dict(self):
        return {
            "data": type(self),
            "_type": f"{TypeCoder.__module__}.{TypeCoder.__name__}"
        }

    @staticmethod
    def from_json(json_object):
        return pydoc.locate(json_object["data"])