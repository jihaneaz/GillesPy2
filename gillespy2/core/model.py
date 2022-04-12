"""
GillesPy2 is a modeling toolkit for biochemical simulation.
Copyright (C) 2019-2021 GillesPy2 developers.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import numpy as np
from typing import Set, Type
from collections import OrderedDict

import gillespy2
from gillespy2.core.assignmentrule import AssignmentRule
from gillespy2.core.events import Event
from gillespy2.core.functiondefinition import FunctionDefinition
from gillespy2.core.parameter import Parameter
from gillespy2.core.raterule import RateRule
from gillespy2.core.reaction import Reaction
from gillespy2.core.species import Species
from gillespy2.core.timespan import TimeSpan
from gillespy2.core.sortableobject import SortableObject
from gillespy2.core.jsonify import Jsonify, TranslationTable
from gillespy2.core.results import Trajectory, Results
from gillespy2.core.gillespyError import (
    SpeciesError,
    ParameterError,
    ModelError,
    SimulationError,
    StochMLImportError,
    InvalidStochMLError
)

try:
    import lxml.etree as eTree

    no_pretty_print = False

except:
    import xml.etree.ElementTree as eTree
    import xml.dom.minidom
    import re
    no_pretty_print = True


def import_SBML(filename, name=None, gillespy_model=None):
    """
    SBML to GillesPy model converter. NOTE: non-mass-action rates
    in terms of concentrations may not be converted for population
    simulation. Use caution when importing SBML.

    :param filename: Path to the SBML file for conversion.
    :type filename: str

    :param name: Name of the resulting model
    :type name: str

    :param gillespy_model: If desired, the SBML model may be added to an existing GillesPy model
    :type gillespy_model: gillespy.Model
    """

    try:
        from gillespy2.sbml.SBMLimport import convert
    except ImportError:
        raise ImportError('SBML conversion not imported successfully')

    return convert(filename, model_name=name, gillespy_model=gillespy_model)


def export_SBML(gillespy_model, filename=None):
    """
    GillesPy model to SBML converter

    :param gillespy_model: GillesPy model to be converted to SBML
    :type gillespy_model: gillespy.Model

    :param filename: Path to the SBML file for conversion
    :type filename: str
    """
    try:
        from gillespy2.sbml.SBMLexport import export
    except ImportError:
        raise ImportError('SBML export conversion not imported successfully')

    return export(gillespy_model, path=filename)


def export_StochSS(gillespy_model, filename=None, return_stochss_model=False):
    """
    GillesPy model to StochSS converter

    :param gillespy_model: GillesPy model to be converted to StochSS
    :type gillespy_model: gillespy.Model

    :param filename: Path to the StochSS file for conversion
    :type filename: str
    """
    try:
        from gillespy2.stochss.StochSSexport import export
    except ImportError:
        raise ImportError('StochSS export conversion not imported successfully')

    return export(gillespy_model, path=filename, return_stochss_model=return_stochss_model)


class Model(SortableObject, Jsonify):
    """
    Representation of a well mixed biochemical model. Contains reactions,
    parameters, species.

    :param name: The name of the model, or an annotation describing it.
    :type name: str

    :param population: The type of model being described. A discrete stochastic model is a
        population model (True), a deterministic model is a concentration model
        (False). Automatic conversion from population to concentration models
        may be used, by setting the volume parameter.
    :type population: bool

    :param volume: The volume of the system matters when converting to from population to
        concentration form. This will also set a parameter "vol" for use in
        custom (i.e. non-mass-action) propensity functions.
    :type volume: float

    :param tspan: The timepoints at which the model should be simulated. If None, a
        default timespan is added. May be set later, see Model.timespan
    :type tspan: numpy ndarray

    :param annotation: Option further description of model
    :type annotation: str
    """

    # reserved names for model species/parameter names, volume, and operators.
    reserved_names = ['vol']
    special_characters = ['[', ']', '+', '-', '*', '/', '.', '^']

    def __init__(self, name="", population=True, volume=1.0, tspan=None, annotation="model"):
        """ Create an empty model. """

        # The name that the model is referenced by (should be a String)
        self.name = name
        self.annotation = annotation

        # Dictionaries with model element objects.
        # Model element names are used as keys.
        self.listOfParameters = OrderedDict()
        self.listOfSpecies = OrderedDict()
        self.listOfReactions = OrderedDict()

        self.listOfAssignmentRules = OrderedDict()
        self.listOfRateRules = OrderedDict()
        self.listOfEvents = OrderedDict()
        self.listOfFunctionDefinitions = OrderedDict()

        # Dictionaries with model element objects.
        # Model element names are used as keys, and values are
        # sanitized versions of the names/formulas.
        # These dictionaries contain sanitized values and are for
        # Internal use only
        self._listOfParameters = OrderedDict()
        self._listOfSpecies = OrderedDict()
        self._listOfReactions = OrderedDict()
        self._listOfAssignmentRules = OrderedDict()
        self._listOfRateRules = OrderedDict()
        self._listOfEvents = OrderedDict()
        self._listOfFunctionDefinitions = OrderedDict()
        # This defines the unit system at work for all numbers in the model
        # It should be a logical error to leave this undefined, subclasses
        # should set it
        if population:
            self.units = "population"
        else:
            self.units = "concentration"
            if volume != 1.0:
                raise ModelError(
                    "Concentration models account for volume implicitly, explicit volume definition is not required. "
                    "Note: concentration models may only be simulated deterministically."
                )

        self.volume = volume

        # Dict that holds flattended parameters and species for
        # evaluation of expressions in the scope of the model.
        self.namespace = OrderedDict([])

        if tspan is None:
            self.tspan = None
        else:
            self.timespan(tspan)

        # Change Jsonify settings to disable private variable
        # JSON hashing and enable automatic translation table gen.
        self._hash_private_vars = False
        self._generate_translation_table = True

    def __str__(self):
        divider = '\n**********\n'

        def decorate(header):
            return '\n' + divider + header + divider

        print_string = self.name
        if len(self.listOfSpecies):
            print_string += decorate('Species')
            for s in sorted(self.listOfSpecies.values()):
                print_string += '\n' + str(s)
        if len(self.listOfParameters):
            print_string += decorate('Parameters')
            for p in sorted(self.listOfParameters.values()):
                print_string += '\n' + str(p)
        if len(self.listOfReactions):
            print_string += decorate('Reactions')
            for r in sorted(self.listOfReactions.values()):
                print_string += '\n' + str(r)
        if len(self.listOfEvents):
            print_string += decorate('Events')
            for e in sorted(self.listOfEvents.values()):
                print_string += '\n' + str(e)
        if len(self.listOfAssignmentRules):
            print_string += decorate('Assignment Rules')
            for ar in sorted(self.listOfAssignmentRules.values()):
                print_string += '\n' + str(ar)
        if len(self.listOfRateRules):
            print_string += decorate('Rate Rules')
            for rr in sorted(self.listOfRateRules.values()):
                print_string += '\n' + str(rr)
        if len(self.listOfFunctionDefinitions):
            print_string += decorate('Function Definitions')
            for fd in sorted(self.listOfFunctionDefinitions.values()):
                print_string += '\n' + str(fd)

        return print_string

    def problem_with_name(self, name):
        if name in Model.reserved_names:
            raise ModelError(
                'Name "{}" is unavailable. It is reserved for internal GillesPy use. Reserved Names: ({}).'.format(name,
                                                                                                                   Model.reserved_names))
        if name in self.listOfSpecies:
            raise ModelError('Name "{}" is unavailable. A species with that name exists.'.format(name))
        if name in self.listOfParameters:
            raise ModelError('Name "{}" is unavailable. A parameter with that name exists.'.format(name))
        if name in self.listOfReactions:
            raise ModelError('Name "{}" is unavailable. A reaction with that name exists.'.format(name))
        if name in self.listOfEvents:
            raise ModelError('Name "{}" is unavailable. An event with that name exists.'.format(name))
        if name in self.listOfRateRules:
            raise ModelError('Name "{}" is unavailable. A rate rule with that name exists.'.format(name))
        if name in self.listOfAssignmentRules:
            raise ModelError('Name "{}" is unavailable. An assignment rule with that name exists.'.format(name))
        if name in self.listOfFunctionDefinitions:
            raise ModelError('Name "{}" is unavailable. A function definition with that name exists.'.format(name))
        if name.isdigit():
            raise ModelError('Name "{}" is unavailable. Names must not be numeric strings.'.format(name))
        for special_character in Model.special_characters:
            if special_character in name:
                raise ModelError(
                    'Name "{}" is unavailable. Names must not contain special characters: {}.'.format(name,
                                                                                                      Model.special_characters))

    def update_namespace(self):
        """ Create a dict with flattened parameter and species objects. """
        self.namespace = OrderedDict([])
        for param in self.listOfParameters:
            self.namespace[param] = self.listOfParameters[param].value

    def add(self, components):
        """
        Adds a component, or list of components to the model. If a list is provided, Species
        and Parameters are added before other components.  Lists may contain any combination
        of accepted types other than lists and do not need to be in any particular order.

        :param components: The component or list of components to be added the the model.
        :type components: Species, Parameters, Reactions, Events, Rate Rules, Assignment Rules, \
                          FunctionDefinitions, and TimeSpan or list

        :returns: The components that were added to the model.
        :rtype: Species, Parameters, Reactions, Events, Rate Rules, Assignment Rules, \
                FunctionDefinitions, and TimeSpan or list

        :raises ModelError: Component is invalid.
        """
        if isinstance(components, list):
            p_types = (Species, Parameter, FunctionDefinition, TimeSpan)
            p_names = (p_type.__name__ for p_type in p_types)

            others = []
            for component in components:
                if isinstance(component, p_types) or type(component).__name__ in p_names:
                    self.add(component)
                else:
                    others.append(component)

            for component in others:
                self.add(component)
        elif isinstance(components, AssignmentRule) or type(components).__name__ == AssignmentRule.__name__:
            self.add_assignment_rule(components)
        elif isinstance(components, Event) or type(components).__name__ == Event.__name__:
            self.add_event(components)
        elif isinstance(components, FunctionDefinition) or type(components).__name__ == FunctionDefinition.__name__:
            self.add_function_definition(components)
        elif isinstance(components, Parameter) or type(components).__name__ == Parameter.__name__:
            self.add_parameter(components)
        elif isinstance(components, RateRule) or type(components).__name__ == RateRule.__name__:
            self.add_rate_rule(components)
        elif isinstance(components, Reaction) or type(components).__name__ == Reaction.__name__:
            self.add_reaction(components)
        elif isinstance(components, Species) or type(components).__name__ == Species.__name__:
            self.add_species(components)
        elif isinstance(components, TimeSpan) or type(components).__name__ == TimeSpan.__name__:
            self.timespan(components)
        else:
            raise ModelError(f"Unsupported component: {type(components)} is not a valid component.")
        return components

    def add_species(self, species):
        """
        Adds a species, or list of species to the model.

        :param species: The species or list of species to be added to the model object
        :type species: gillespy2.Species | list of gillespy2.Species

        :returns: The species or list of species that were added to the model.
        :rtype: gillespy2.Species | list of gillespy2.Species

        :raises ModelError: If an invalid species is provided or if Species.validate fails.
        """
        if isinstance(species, list):
            for spec in sorted(species):
                self.add_species(spec)
        elif isinstance(species, Species) or type(species).__name__ == "Species":
            try:
                species.validate()
                self.problem_with_name(species.name)
                self.listOfSpecies[species.name] = species
                self._listOfSpecies[species.name] = f'S{len(self._listOfSpecies)}'
            except SpeciesError as err:
                errmsg = f"Could not add species: {species.name}, Reason given: {err}"
                raise ModelError(errmsg) from err
        else:
            errmsg = f"species must be of type Species or list of Species not {type(species)}"
            raise ModelError(errmsg)
        return species

    def delete_species(self, name):
        """
        Removes a species object by name.

        :param name: Name of the species object to be removed
        :type name: str
        """
        self.listOfSpecies.pop(name)
        if name in self._listOfSpecies:
            self._listOfSpecies.pop(name)

    def delete_all_species(self):
        """
        Removes all species from the model object.
        """
        self.listOfSpecies.clear()
        self._listOfSpecies.clear()

    def get_species(self, name):
        """
        Returns a species object by name.

        :param name: Name of the species object to be returned
        :type name: str

        :returns: The specified species object.
        :rtype: gillespy2.Species

        :raises ModelError: If the species is not part of the model.
        """
        if name not in self.listOfSpecies:
            raise ModelError(f"Species {name} could not be found in the model.")
        return self.listOfSpecies[name]

    def get_all_species(self):
        """
        :returns: A dict of all species in the model, in the form: {name : species object}.
        :rtype: OrderedDict
        """
        return self.listOfSpecies

    def sanitized_species_names(self):
        """
        Generate a dictionary mapping user chosen species names to simplified formats which will be used
        later on by GillesPySolvers evaluating reaction propensity functions.

        :returns: the dictionary mapping user species names to their internal GillesPy notation.
        """
        species_name_mapping = OrderedDict([])
        for i, name in enumerate(self.listOfSpecies.keys()):
            species_name_mapping[name] = 'S[{}]'.format(i)
        return species_name_mapping

    def add_parameter(self, parameters):
        """
        Adds a parameter, or list of parameters to the model.

        :param parameters:  The parameter or list of parameters to be added to the model object.
        :type parameters: gillespy2.Parameter | list of gillespy2.Parameter

        :returns: A parameter or list of Parameters that were added to the model.
        :rtype: gillespy2.Parameter | list of gillespy2.Parameter

        :raises ModelError: If an invalid parameter is provided or if Parameter.validate fails.
        """
        if isinstance(parameters, list):
            for param in sorted(parameters):
                self.add_parameter(param)
        elif isinstance(parameters, Parameter) or type(parameters).__name__ == 'Parameter':
            self.problem_with_name(parameters.name)
            self.resolve_parameter(parameters)
            self.listOfParameters[parameters.name] = parameters
            self._listOfParameters[parameters.name] = f'P{len(self._listOfParameters)}'
        else:
            errmsg = f"parameters must be of type Parameter or list of Parameter not {type(parameters)}"
            raise ModelError(errmsg)
        return parameters

    def delete_parameter(self, name):
        """
        Removes a parameter object by name.

        :param name: Name of the parameter object to be removed.
        :type name: str
        """
        self.listOfParameters.pop(name)
        if name in self._listOfParameters:
            self._listOfParameters.pop(name)

    def delete_all_parameters(self):
        """
        Removes all parameters from model object.
        """
        self.listOfParameters.clear()
        self._listOfParameters.clear()

    def get_parameter(self, name):
        """
        Returns a parameter object by name.

        :param name: Name of the parameter object to be returned
        :type name: str

        :returns: The specified parameter object.
        :rtype: gillespy2.Parameter

        :raises ModelError: If the parameter is not part of the model.
        """
        if name not in self.listOfParameters:
            raise ModelError(f"Parameter {name} could not be found in the model.")
        return self.listOfParameters[name]

    def get_all_parameters(self):
        """
        :returns: A dict of all parameters in the model, in the form: {name : parameter object}
        :rtype: OrderedDict
        """
        return self.listOfParameters

    def resolve_parameter(self, parameter):
        """
        Internal function:
        attempt to resolve the given parameter expressions to scalar floats.
        This methods must be called before exporting the model.

        :param parameter: The target parameter to resolve.
        :type parameter: gillespy2.Parameter

        :raises ModelError: If the parameter can't be resolved.
        """
        try:
            parameter.validate()
            self.update_namespace()
            parameter._evaluate(self.namespace)
        except ParameterError as err:
            raise ModelError(f"Could not add/resolve parameter: {parameter.name}, Reason given: {err}") from err

    def resolve_all_parameters(self):
        """
        Internal function:
        attempt to resolve all parameter expressions to scalar floats.
        This methods must be called before exporting the model.
        """
        for _, parameter in self.listOfParameters.items():
            self.resolve_parameter(parameter)

    def sanitized_parameter_names(self):
        """
        Generate a dictionary mapping user chosen parameter names to simplified formats which will be used
        later on by GillesPySolvers evaluating reaction propensity functions.

        :returns: the dictionary mapping user parameter names to their internal GillesPy notation.
        """
        parameter_name_mapping = OrderedDict()
        parameter_name_mapping['vol'] = 'V'
        for i, name in enumerate(self.listOfParameters.keys()):
            if name not in parameter_name_mapping:
                parameter_name_mapping[name] = 'P{}'.format(i)
        return parameter_name_mapping

    def set_parameter(self, p_name, expression):
        """
        Set the value of an existing parameter "pname" to "expression" (deprecated).

        :param p_name: Name of the parameter whose value will be set.
        :type p_name: str

        :param expression: String that may be executed in C, describing the value of the
            parameter. May reference other parameters by name. (e.g. "k1*4")
        :type expression: str
        """
        from gillespy2.core import log
        log.warning(
            """
            Model.set_parameter has been deprecated.  Future releases of GillesPy2 may
            not support this feature.  Parameter.expression should only be set in the constructor.
            """
        )

        parameter = self.listOfParameters[p_name]
        parameter.expression = expression
        self.resolve_parameter(parameter)

    def delete_reaction(self, name):
        """
        Removes a reaction object by name.

        :param name: Name of the reaction object to be removed.
        :type name: str
        """
        self.listOfReactions.pop(name)
        if name in self._listOfReactions:
            self._listOfReactions.pop(name)

    def delete_all_reactions(self):
        """
        Removes all reactions from the model object.
        """
        self.listOfReactions.clear()
        self._listOfReactions.clear()

    def add_reaction(self, reactions):
        """
        Adds a reaction, or list of reactions to the model.

        :param reactions: The reaction or list of reactions to be added to the model object
        :type reactions: gillespy2.Reaction | list of gillespy2.Reaction

        :returns: The reaction or list of reactions that were added to the model.
        :rtype: gillespy2.Reaction | list of gillespy2.Reaction

        :raises ModelError: If an invalid reaction is provided or if Reaction.validate fails.
        """
        if isinstance(reactions, list):
            for reaction in sorted(reactions):
                self.add_reaction(reaction)
        elif isinstance(reactions, Reaction) or type(reactions).__name__ == "Reaction":
            self.problem_with_name(reactions.name)
            self.resolve_reaction(reactions)
            self.listOfReactions[reactions.name] = reactions
            # Build Sanitized reaction as well
            sanitized_reaction = reactions._create_sanitized_reaction(
                len(self.listOfReactions), self._listOfSpecies, self._listOfParameters
            )
            self._listOfReactions[reactions.name] = sanitized_reaction
        else:
            errmsg = f"reactions must be of type Reaction or list of Reaction not {type(reactions)}"
            raise ModelError(errmsg)
        return reactions

    def get_reaction(self, name):
        """
        Returns a reaction object by name.

        :param name: Name of the reaction object to be returned
        :type name: str

        :returns: The specified reaction object.
        :rtype: gillespy2.Reaction

        :raises ModelError: If the reaction is not part of the model.
        """
        if name not in self.listOfReactions:
            raise ModelError(f"Reaction {name} could not be found in the model.")
        return self.listOfReactions[name]

    def get_all_reactions(self):
        """
        :returns: A dict of all reaction in the model, in the form: {name : reaction object}.
        :rtype: OrderedDict
        """
        return self.listOfReactions

    def resolve_reaction(self, reaction):
        """
        Internal function:
        Ensure that the rate and all reactants and products are present in the model
        for the given reaction.  This methods must be called before exporting the model.

        :param reaction: The target reaction to resolve.
        :type reaction: gillespy2.Reaction

        :raises ModelError: If the reaction can't be resolved.
        """
        try:
            reaction.validate()

            # If the rate parameter exists in the reaction, confirm that it is a part of the model
            if reaction.marate is not None:
                name = reaction.marate if isinstance(reaction.marate, str) else reaction.marate.name
                reaction.marate = self.get_parameter(name)

            # Confirm that all species in reactants are part of the model
            for species in list(reaction.reactants.keys()):
                stoichiometry = reaction.reactants[species]
                name = species if isinstance(species, str) else species.name
                stoich_spec = self.get_species(name)
                if stoich_spec not in reaction.reactants:
                    reaction.reactants[stoich_spec] = stoichiometry
                    del reaction.reactants[species]

            # Confirm that all species in products are part of the model
            for species in list(reaction.products.keys()):
                stoichiometry = reaction.products[species]
                name = species if isinstance(species, str) else species.name
                stoich_spec = self.get_species(name)
                if stoich_spec not in reaction.products:
                    reaction.products[stoich_spec] = stoichiometry
                    del reaction.products[species]
        except ModelError as err:
            raise ModelError(f"Could not add/resolve reaction: {reaction.name}, Reason given: {err}") from err

    def resolve_all_reactions(self):
        """
        Internal function:
        Ensure that the rate and all reactants and products are present in the model
        for all reactions.  This methods must be called before exporting the model.
        """
        for _, reaction in self.listOfReactions.items():
            self.resolve_reaction(reaction)

    def validate_reactants_and_products(self, reactions):
        """
        Internal function (deprecated):
        Ensure that the rate and all reactants and products are present in the model
        for the given reaction.  This methods must be called before exporting the model.

        :param reaction: The target reaction to resolve.
        :type reaction: gillespy2.Reaction

        :raises ModelError: If the reaction can't be resolved.
        """
        from gillespy2.core import log
        log.warning(
            """
            Model.validate_reactants_and_products has been deprecated. Future releases of
            GillesPy2 may not support this feature.  Use Model.resolve_reaction instead.
            """
        )

        self.resolve_reaction(reactions)

    def make_translation_table(self):
        from collections import ChainMap

        species = self.listOfSpecies.values()
        reactions = self.listOfReactions.values()
        parameters = self.listOfParameters.values()
        assignments = self.listOfAssignmentRules.values()
        rates = self.listOfRateRules.values()
        events = self.listOfEvents.values()
        functions = self.listOfFunctionDefinitions.values()

        # A translation table is used to anonymize user-defined variable names and formulas into generic counterparts.
        translation_table = dict(ChainMap(

            # Build translation mappings for user-defined variable names.
            dict({ self.name: "Model" }),
            dict(zip((str(x.name) for x in species), (f"S_{x + 100}" for x in range(0, len(species))))),
            dict(zip((str(x.name) for x in reactions), (f"R_{x + 100}" for x in range(0, len(reactions))))),
            dict(zip((str(x.name) for x in parameters), (f"P_{x + 100}" for x in range(0, len(parameters))))),
            dict(zip((str(x.name) for x in assignments), (f"AR_{x + 100}" for x in range(0, len(assignments))))),
            dict(zip((str(x.name) for x in rates), (f"RR_{x + 100}" for x in range(0, len(rates))))),
            dict(zip((str(x.name) for x in events), (f"E_{x + 100}" for x in range(0, len(events))))),
            dict(zip((str(x.name) for x in functions), (f"F_{x + 100}" for x in range(0, len(functions))))),
        ))

        return TranslationTable(to_anon=translation_table)

    def serialize(self):
        """ Serializes the Model object to valid StochML. """
        self.resolve_all_parameters()
        doc = StochMLDocument().from_model(self)
        return doc.to_string()

    def set_units(self, units):
        """
        Sets the units of the model to either "population" or "concentration"

        :param units: Either "population" or "concentration"
        :type units: str
        """
        if units.lower() == 'concentration' or units.lower() == 'population':
            self.units = units.lower()
        else:
            raise ModelError("units must be either concentration or population (case insensitive)")

    def add_rate_rule(self, rate_rules):
        """
        Adds a rate rule, or list of rate rules to the model.

        :param rate_rules: The rate rule or list of rate rule objects to be added to the model object.
        :type rate_rules: RateRule, or list of RateRules
        """
        if isinstance(rate_rules, list):
            for rr in sorted(rate_rules):
                self.add_rate_rule(rr)
        else:
            try:
                self.problem_with_name(rate_rules.name)
                if len(self.listOfAssignmentRules) != 0:
                    for i in self.listOfAssignmentRules.values():
                        if rate_rules.variable == i.variable:
                            raise ModelError("Duplicate variable in rate_rules AND assignment_rules: {0}".
                                             format(rate_rules.variable))
                for i in self.listOfRateRules.values():
                    if rate_rules.variable == i.variable:
                        raise ModelError("Duplicate variable in rate_rules: {0}".format(rate_rules.variable))
                if rate_rules.name in self.listOfRateRules:
                    raise ModelError("Duplicate name of rate_rule: {0}".format(rate_rules.name))
                if rate_rules.formula == '':
                    raise ModelError('Invalid Rate Rule. Expression must be a non-empty string value')
                if rate_rules.variable == None:
                    raise ModelError('A GillesPy2 Rate Rule must be associated with a valid variable')
                if isinstance(rate_rules.variable, str):
                    v = rate_rules.variable
                    if v not in self.listOfSpecies and v not in self.listOfParameters:
                        raise ModelError(
                            'Invalid variable entered for Rate Rule: {}'.format(rate_rules.name))

                self.listOfRateRules[rate_rules.name] = rate_rules
                sanitized_rate_rule = RateRule(name='RR{}'.format(len(self._listOfRateRules)))
                sanitized_rate_rule.formula = rate_rules.sanitized_formula(self._listOfSpecies,
                                                                           self._listOfParameters)
                self._listOfRateRules[rate_rules.name] = sanitized_rate_rule
            except Exception as e:
                raise ParameterError("Error using {} as a Rate Rule. Reason given: {}".format(rate_rules, e))
        return rate_rules

    def add_event(self, event):
        """
        Adds an event, or list of events to the model.

        :param event: The event or list of event objects to be added to the model object.
        :type event: Event, or list of Events
        """

        if isinstance(event, list):
            for e in event:
                self.add_event(e)
        else:
            try:
                self.problem_with_name(event.name)
                if event.trigger is None or not hasattr(event.trigger, 'expression'):
                    raise ModelError(
                        'An Event must contain a valid trigger.')
                for a in event.assignments:
                    if isinstance(a.variable, str):
                        a.variable = self.get_element(a.variable)
                self.listOfEvents[event.name] = event
            except Exception as e:
                raise ParameterError("Error using {} as Event. Reason given: {}".format(event, e))
        return event

    def add_function_definition(self, function_definitions):
        """
        Add FunctionDefinition or list of FunctionDefinitions

        :param function_definitions: The FunctionDefinition, or list of FunctionDefinitions to be added to the model
            object.
        :type function_definitions: FunctionDefinition or list of FunctionDefinitions.
        """
        if isinstance(function_definitions, list):
            for fd in function_definitions:
                self.add_function_definition(fd)
        else:
            try:
                self.problem_with_name(function_definitions.name)
                self.listOfFunctionDefinitions[function_definitions.name] = function_definitions
            except Exception as e:
                raise ParameterError(
                    "Error using {} as a Function Definition. Reason given: {}".format(function_definitions, e))

    def add_assignment_rule(self, assignment_rules):
        """
        Add AssignmentRule or list of AssignmentRules to the model object.

        :param assignment_rules: The AssignmentRule or list of AssignmentRules to be added to the model object.
        :type assignment_rules: AssignmentRule or list of AssignmentRules
        """
        if isinstance(assignment_rules, list):
            for ar in assignment_rules:
                self.add_assignment_rule(ar)
        else:
            try:
                self.problem_with_name(assignment_rules.name)
                if len(self.listOfRateRules) != 0:
                    for i in self.listOfRateRules.values():
                        if assignment_rules.variable == i.variable:
                            raise ModelError("Duplicate variable in rate_rules AND assignment_rules: {0}".
                                             format(assignment_rules.variable))
                for i in self.listOfAssignmentRules.values():
                    if assignment_rules.variable == i.variable:
                        raise ModelError("Duplicate variable in assignment_rules: {0}"
                                         .format(assignment_rules.variable))
                if assignment_rules.name in self.listOfAssignmentRules:
                    raise ModelError("Duplicate name in assignment_rules: {0}".format(assignment_rules.name))
                if assignment_rules.formula == '':
                    raise ModelError('Invalid Assignment Rule. Expression must be a non-empty string value')
                if assignment_rules.variable == None:
                    raise ModelError('A GillesPy2 Rate Rule must be associated with a valid variable')

                self.listOfAssignmentRules[assignment_rules.name] = assignment_rules
            except Exception as e:
                raise ParameterError("Error using {} as a Assignment Rule. Reason given: {}".format(assignment_rules, e))

    def timespan(self, time_span):
        """
        Set the time span of simulation. StochKit does not support non-uniform
        timespans. 

        :param time_span: Evenly-spaced list of times at which to sample the species populations during the simulation. 
            Best to use the form gillespy2.TimeSpan(np.linspace(<start time>, <end time>, <number of time-points, inclusive>))
        :type time_span: gillespy2.TimeSpan | iterator
        """        
        if isinstance(time_span, TimeSpan) or type(time_span).__name__ == "TimeSpan":
            self.tspan = time_span
        else:
            self.tspan = TimeSpan(time_span)

    def get_event(self, ename):
        """
        :param ename: Name of Event to get
        :returns: Event object
        """
        return self.listOfEvents[ename]

    def get_all_events(self):
        """
        :returns: dict of all Event objects
        """
        return self.listOfEvents

    def delete_event(self, name):
        """
        Removes specified Event from model

        :param name: Name of Event to be removed.
        :type name: str
        """
        self.listOfEvents.pop(name)
        if name in self._listOfEvents:
            self._listOfEvents.pop(name)

    def delete_all_events(self):
        """
        Clears models events
        """
        self.listOfEvents.clear()
        self._listOfEvents.clear()

    def get_rate_rule(self, rname):
        """
        :param rname: Name of Rate Rule to get
        :returns: RateRule object
        """
        return self.listOfRateRules[rname]

    def get_all_rate_rules(self):
        """
        :returns: dict of all Rate Rule objects
        """
        return self.listOfRateRules

    def delete_rate_rule(self, name):
        """
        Removes specified Rate Rule from model

        :param name: Name of Rate Rule to be removed.
        :type name: str
        """
        self.listOfRateRules.pop(name)
        if name in self._listOfRateRules:
            self._listOfRateRules.pop(name)

    def delete_all_rate_rules(self):
        """
        Clears all of models Rate Rules
        """
        self.listOfRateRules.clear()
        self._listOfRateRules.clear()

    def get_assignment_rule(self, aname):
        """
        :param aname: Name of Assignment Rule to get
        :returns: Assignment Rule object
        """
        return self.listOfAssignmentRules[aname]

    def get_all_assignment_rules(self):
        """
        :returns: dict of models Assignment Rules
        """
        return self.listOfAssignmentRules

    def delete_assignment_rule(self, name):
        """
        Removes an assignment rule from a model

        :param name: Name of AssignmentRule object to be removed from model.
        :type name: str
        """
        self.listOfAssignmentRules.pop(name)
        if name in self._listOfAssignmentRules:
            self._listOfAssignmentRules.pop(name)

    def delete_all_assignment_rules(self):
        """
        Clears all assignment rules from model
        """
        self.listOfAssignmentRules.clear()
        self._listOfAssignmentRules.clear()

    def get_function_definition(self, fname):
        """
        :param fname: name of Function to get
        :returns: FunctionDefinition object
        """
        return self.listOfFunctionDefinitions[fname]

    def get_all_function_definitions(self):
        """
        :returns: Dict of models function definitions
        """
        return self.listOfFunctionDefinitions

    def delete_function_definition(self, name):
        """
        Removes specified Function Definition from model

        :param name: Name of Function Definition to be removed
        :type name: str
        """
        self.listOfFunctionDefinitions.pop(name)
        if name in self._listOfFunctionDefinitions:
            self._listOfFunctionDefinitions.pop(name)

    def delete_all_function_definitions(self):
        """
        Clears all Function Definitions from a model
        """
        self.listOfFunctionDefinitions.clear()
        self._listOfFunctionDefinitions.clear()

    def get_element(self, ename):
        """
        Get element specified by name.

        :param ename: name of element to search for
        :returns: value of element, or 'element not found'
        """
        if ename in self.listOfReactions:
            return self.get_reaction(ename)
        if ename in self.listOfSpecies:
            return self.get_species(ename)
        if ename in self.listOfParameters:
            return self.get_parameter(ename)
        if ename in self.listOfEvents:
            return self.get_event(ename)
        if ename in self.listOfRateRules:
            return self.get_rate_rule(ename)
        if ename in self.listOfAssignmentRules:
            return self.get_assignment_rule(ename)
        if ename in self.listOfFunctionDefinitions:
            return self.get_function_definition(ename)
        raise ModelError(f"model.get_element(): element={ename} not found")


    def get_best_solver(self):
        """
        Finds best solver for the users simulation. Currently, AssignmentRules, RateRules, FunctionDefinitions,
        Events, and Species with a dynamic, or continuous population must use the TauHybridSolver.

        :param precompile: If True, and the model contains no AssignmentRules, RateRules, FunctionDefinitions, Events,
            or Species with a dynamic or continuous population, it will choose SSACSolver
        :type precompile: bool

        :returns: gillespy2.gillespySolver
        """
        from gillespy2.solvers.numpy import can_use_numpy
        hybrid_check = False
        chybrid_check = True
        if len(self.get_all_rate_rules())  or len(self.get_all_events()):
            hybrid_check = True
        if len(self.get_all_assignment_rules()) or len(self.get_all_function_definitions()):
            hybrid_check = True
            chybrid_check = False

        if len(self.get_all_species()) and hybrid_check == False:
            for i in self.get_all_species():
                tempMode = self.get_species(i).mode
                if tempMode == 'dynamic' or tempMode == 'continuous':
                    hybrid_check = True
                    break

        from gillespy2.solvers.cpp.build.build_engine import BuildEngine
        can_use_cpp = not len(BuildEngine.get_missing_dependencies())

        if not can_use_cpp and not can_use_numpy:
            raise ModelError('Dependency Error, cannot run model.')

        if can_use_cpp and hybrid_check and chybrid_check:
            from gillespy2 import TauHybridCSolver
            return TauHybridCSolver
        elif can_use_numpy and hybrid_check:
            from gillespy2 import TauHybridSolver
            return TauHybridSolver
        
        if can_use_cpp is False and can_use_numpy and not hybrid_check:
            from gillespy2 import NumPySSASolver
            return NumPySSASolver

        else:
            from gillespy2 import SSACSolver
            return SSACSolver

    def get_best_solver_algo(self, algorithm):
        """
        If user has specified a particular algorithm, we return either the Python or C++ version of that algorithm
        """
        from gillespy2.solvers.numpy import can_use_numpy
        from gillespy2.solvers.cpp.build.build_engine import BuildEngine
        can_use_cpp = not len(BuildEngine.get_missing_dependencies())
        chybrid_check = True
        if len(self.get_all_assignment_rules()) or len(self.get_all_function_definitions()):
            chybrid_check = False

        if not can_use_cpp and can_use_numpy:
            raise ModelError("Please install C++ or Numpy to use GillesPy2 solvers.")

        if algorithm == 'Tau-Leaping':
            if can_use_cpp:
                from gillespy2 import TauLeapingCSolver
                return TauLeapingCSolver
            else:
                from gillespy2 import TauLeapingSolver
                return TauLeapingSolver

        elif algorithm == 'SSA':
            if can_use_cpp:
                from gillespy2 import SSACSolver
                return SSACSolver
            else:
                from gillespy2 import NumPySSASolver
                return NumPySSASolver

        elif algorithm == 'ODE':
            if can_use_cpp:
                from gillespy2 import ODECSolver
                return ODECSolver
            else:
                from gillespy2 import ODESolver
                return ODESolver

        elif algorithm == 'Tau-Hybrid':
            if can_use_cpp and chybrid_check:
                from gillespy2 import TauHybridCSolver
                return TauHybridCSolver
            else:
                from gillespy2 import TauHybridSolver
                return TauHybridSolver

        elif algorithm == 'CLE':
            from gillespy2 import CLESolver
            return CLESolver
            
        else:
            raise ModelError("Invalid value for the argument 'algorithm' entered. "
                             "Please enter 'SSA', 'ODE', 'CLE', 'Tau-leaping', or 'Tau-Hybrid'.")

    def get_model_features(self) -> "Set[Type]":
        """
        Determine what solver-specific model features are present on the model.
        Used to validate that the model is compatible with the given solver.

        :returns: Set containing the classes of every solver-specific feature present on the model.
        """
        features = set()
        if len(self.listOfEvents):
            features.add(gillespy2.Event)
        if len(self.listOfRateRules):
            features.add(gillespy2.RateRule)
        if len(self.listOfAssignmentRules):
            features.add(gillespy2.AssignmentRule)
        if len(self.listOfFunctionDefinitions):
            features.add(gillespy2.FunctionDefinition)
        return features

    def run(self, solver=None, timeout=0, t=None, increment=None, show_labels=True, algorithm=None,
            **solver_args):
        """
        Function calling simulation of the model. There are a number of
        parameters to be set here.

        :param solver: The solver by which to simulate the model. This solver object may
            be initialized separately to specify an algorithm. Optional, defaults to ssa solver.
        :type solver: gillespy.GillesPySolver

        :param timeout: Allows a time_out value in seconds to be sent to a signal handler, restricting simulation run-time
        :type timeout: int

        :param t: End time of simulation
        :type t: int

        :param solver_args: Solver-specific arguments to be passed to solver.run()

        :param algorithm: Specify algorithm ('ODE', 'Tau-Leaping', or 'SSA') for GillesPy2 to automatically pick best solver using that algorithm.
        :type algorithm: str

        :returns:  If show_labels is False, returns a numpy array of arrays of species population data. If show_labels is
            True,returns a Results object that inherits UserList and contains one or more Trajectory objects that
            inherit UserDict. Results object supports graphing and csv export.

        To pause a simulation and retrieve data before the simulation, keyboard interrupt the simulation by pressing
        control+c or pressing stop on a jupyter notebook. To resume a simulation, pass your previously ran results
        into the run method, and set t = to the time you wish the resuming simulation to end (run(resume=results, t=x)).
        
        **Pause/Resume is only supported for SINGLE TRAJECTORY simulations. T MUST BE SET OR UNEXPECTED BEHAVIOR MAY OCCUR.**
        """

        if not show_labels:
            from gillespy2.core import log
            log.warning('show_labels = False is deprecated. Future releases of GillesPy2 may not support this feature.')

        if solver is None:
            if algorithm is not None:
                solver = self.get_best_solver_algo(algorithm)
            else:
                solver = self.get_best_solver()

        if not hasattr(solver, "is_instantiated"):
            try:
                sol_kwargs = {'model': self}
                if "CSolver" in solver.name and \
                    ("resume" in solver_args or "variables" in solver_args or "live_output" in solver_args):
                    sol_kwargs['variable'] = True
                solver = solver(**sol_kwargs)
            except Exception as err:
                raise SimulationError(f"{solver} is not a valid solver.  Reason Given: {err}.") from err

        try:
            return solver.run(t=t, increment=increment, timeout=timeout, **solver_args)
        except Exception as e:
            raise SimulationError(
                "argument 'solver={}' to run() failed.  Reason Given: {}".format(solver, e)
            ) from e


class StochMLDocument():
    """ Serializiation and deserialization of a Model to/from
        the native StochKit2 XML format. """

    def __init__(self):
        # The root element
        self.document = eTree.Element("Model")
        self.annotation = None

    @classmethod
    def from_model(cls, model):
        """
        Creates an StochKit XML document from an exisiting Model object.
        This method assumes that all the parameters in the model are already
        resolved to scalar floats (see Model.resolveParamters).

        Note, this method is intended to be used internally by the models
        'serialization' function, which performs additional operations and
        tests on the model prior to writing out the XML file. 
        
        You should NOT do:

        .. code-block:: python

            document = StochMLDocument.fromModel(model)
            print document.toString()

        You SHOULD do:

        .. code-block:: python

            print model.serialize()

        """

        # Description
        md = cls()

        d = eTree.Element('Description')

        #
        if model.units.lower() == "concentration":
            d.set('units', model.units.lower())

        d.text = model.annotation
        md.document.append(d)

        # Number of Reactions
        nr = eTree.Element('NumberOfReactions')
        nr.text = str(len(model.listOfReactions))
        md.document.append(nr)

        # Number of Species
        ns = eTree.Element('NumberOfSpecies')
        ns.text = str(len(model.listOfSpecies))
        md.document.append(ns)

        # Species
        spec = eTree.Element('SpeciesList')
        for sname in model.listOfSpecies:
            spec.append(md.__species_to_element(model.listOfSpecies[sname]))
        md.document.append(spec)

        # Parameters
        params = eTree.Element('ParametersList')
        for pname in model.listOfParameters:
            params.append(md.__parameter_to_element(
                model.listOfParameters[pname]))

        params.append(md.__parameter_to_element(Parameter(name='vol', expression=model.volume)))

        md.document.append(params)

        # Reactions
        reacs = eTree.Element('ReactionsList')
        for rname in model.listOfReactions:
            reacs.append(md.__reaction_to_element(model.listOfReactions[rname], model.volume))
        md.document.append(reacs)

        return md

    @classmethod
    def from_file(cls, filepath):
        """ Intializes the document from an exisiting native StochKit XML
        file read from disk. """
        tree = eTree.parse(filepath)
        root = tree.getroot()
        md = cls()
        md.document = root
        return md

    @classmethod
    def from_string(cls, string):
        """ Intializes the document from an exisiting native StochKit XML
        file read from disk. """
        root = eTree.fromString(string)

        md = cls()
        md.document = root
        return md

    def to_model(self, name):
        """ Instantiates a Model object from a StochMLDocument. """

        # Empty model
        model = Model(name=name)
        root = self.document

        # Try to set name from document
        if model.name == "":
            name = root.find('Name')
            if name.text is None:
                raise NameError("The Name cannot be none")
            else:
                model.name = name.text

        # Set annotiation
        ann = root.find('Description')
        if ann is not None:
            units = ann.get('units')

            if units:
                units = units.strip().lower()

            if units == "concentration":
                model.units = "concentration"
            elif units == "population":
                model.units = "population"
            else:  # Default
                model.units = "population"

            if ann.text is None:
                model.annotation = ""
            else:
                model.annotation = ann.text

        # Set units
        units = root.find('Units')
        if units is not None:
            if units.text.strip().lower() == "concentration":
                model.units = "concentration"
            elif units.text.strip().lower() == "population":
                model.units = "population"
            else:  # Default
                model.units = "population"

        # Create parameters
        for px in root.iter('Parameter'):
            name = px.find('Id').text
            expr = px.find('Expression').text
            if name.lower() == 'vol' or name.lower() == 'volume':
                model.volume = float(expr)
            else:
                p = Parameter(name, expression=expr)
                # Try to evaluate the expression in the empty namespace
                # (if the expr is a scalar value)
                p._evaluate()
                model.add_parameter(p)

        # Create species
        for spec in root.iter('Species'):
            name = spec.find('Id').text
            val = spec.find('InitialPopulation').text
            if '.' in val:
                val = float(val)
            else:
                val = int(val)
            s = Species(name, initial_value=val)
            model.add_species([s])

        # The namespace_propensity for evaluating the propensity function
        # for reactions must contain all the species and parameters.
        namespace_propensity = OrderedDict()
        all_species = model.get_all_species()
        all_parameters = model.get_all_parameters()

        for param in all_species:
            namespace_propensity[param] = all_species[param].initial_value

        for param in all_parameters:
            namespace_propensity[param] = all_parameters[param].value

        # Create reactions
        for reac in root.iter('Reaction'):
            try:
                name = reac.find('Id').text
            except:
                raise InvalidStochMLError("Reaction has no name.")

            reaction = Reaction(name=name, reactants={}, products={})

            # Type may be 'mass-action','customized'
            try:
                type = reac.find('Type').text
            except:
                raise InvalidStochMLError("No reaction type specified.")

            reactants = reac.find('Reactants')
            try:
                for ss in reactants.iter('SpeciesReference'):
                    specname = ss.get('id')
                    # The stochiometry should be an integer value, but some
                    # exising StoxhKit models have them as floats. This is
                    # why we need the slightly odd conversion below.
                    stoch = int(float(ss.get('stoichiometry')))
                    # Select a reference to species with name specname
                    sref = model.listOfSpecies[specname]
                    try:
                        # The sref list should only contain one element if
                        # the XML file is valid.
                        reaction.reactants[sref] = stoch
                    except Exception as e:
                        StochMLImportError(e)
            except:
                # Yes, this is correct. 'reactants' can be None
                pass

            products = reac.find('Products')
            try:
                for ss in products.iter('SpeciesReference'):
                    specname = ss.get('id')
                    stoch = int(float(ss.get('stoichiometry')))
                    sref = model.listOfSpecies[specname]
                    try:
                        # The sref list should only contain one element if
                        # the XML file is valid.
                        reaction.products[sref] = stoch
                    except Exception as e:
                        raise StochMLImportError(e)
            except:
                # Yes, this is correct. 'products' can be None
                pass

            if type == 'mass-action':
                reaction.massaction = True
                reaction.type = 'mass-action'
                # If it is mass-action, a parameter reference is needed.
                # This has to be a reference to a species instance. We
                # explicitly disallow a scalar value to be passed as the
                # parameter.
                try:
                    ratename = reac.find('Rate').text
                    try:
                        reaction.marate = model.listOfParameters[ratename]
                    except KeyError as k:
                        # No paramter name is given. This is a valid use case
                        # in StochKit. We generate a name for the paramter,
                        # and create a new parameter instance. The parameter's
                        # value should now be found in 'ratename'.
                        generated_rate_name = "Reaction_" + name + \
                                              "_rate_constant"
                        p = Parameter(name=generated_rate_name,
                                      expression=ratename)
                        # Try to evaluate the parameter to set its value
                        p._evaluate()
                        model.add_parameter(p)
                        reaction.marate = model.listOfParameters[
                            generated_rate_name]

                    reaction.create_mass_action()
                except Exception as e:
                    raise
            elif type == 'customized':
                try:
                    propfunc = reac.find('PropensityFunction').text
                except Exception as e:
                    raise InvalidStochMLError(
                        "Found a customized propensity function, but no expression was given. {}".format(e))
                reaction.propensity_function = propfunc
                reaction.ode_propensity_function = propfunc
            else:
                raise InvalidStochMLError(
                    "Unsupported or no reaction type given for reaction" + name)

            model.add_reaction(reaction)

        return model

    def to_string(self):
        """ Returns  the document as a string. """
        try:
            doc = eTree.tostring(self.document, pretty_print=True)
            return doc.decode("utf-8")
        except:
            # Hack to print pretty xml without pretty-print
            # (requires the lxml module).
            doc = eTree.tostring(self.document)
            xmldoc = xml.dom.minidom.parseString(doc)
            uglyXml = xmldoc.toprettyxml(indent='  ')
            text_re = re.compile(">\n\s+([^<>\s].*?)\n\s+</", re.DOTALL)
            prettyXml = text_re.sub(">\g<1></", uglyXml)
            return prettyXml

    def __species_to_element(self, S):
        e = eTree.Element('Species')
        idElement = eTree.Element('Id')
        idElement.text = S.name
        e.append(idElement)

        if hasattr(S, 'description'):
            descriptionElement = eTree.Element('Description')
            descriptionElement.text = S.description
            e.append(descriptionElement)

        initialPopulationElement = eTree.Element('InitialPopulation')
        initialPopulationElement.text = str(S.initial_value)
        e.append(initialPopulationElement)

        return e

    def __parameter_to_element(self, P):
        e = eTree.Element('Parameter')
        idElement = eTree.Element('Id')
        idElement.text = P.name
        e.append(idElement)
        expressionElement = eTree.Element('Expression')
        expressionElement.text = str(P.value)
        e.append(expressionElement)
        return e

    def __reaction_to_element(self, R, model_volume):
        e = eTree.Element('Reaction')

        idElement = eTree.Element('Id')
        idElement.text = R.name
        e.append(idElement)

        descriptionElement = eTree.Element('Description')
        descriptionElement.text = self.annotation
        e.append(descriptionElement)

        # StochKit2 wants a rate for mass-action propensites
        if R.massaction and model_volume == 1.0:
            rateElement = eTree.Element('Rate')
            # A mass-action reactions should only have one parameter
            rateElement.text = R.marate.name
            typeElement = eTree.Element('Type')
            typeElement.text = 'mass-action'
            e.append(typeElement)
            e.append(rateElement)

        else:
            typeElement = eTree.Element('Type')
            typeElement.text = 'customized'
            e.append(typeElement)
            functionElement = eTree.Element('PropensityFunction')
            functionElement.text = R.propensity_function
            e.append(functionElement)

        reactants = eTree.Element('Reactants')

        for reactant, stoichiometry in R.reactants.items():
            srElement = eTree.Element('SpeciesReference')
            srElement.set('id', str(reactant.name))
            srElement.set('stoichiometry', str(stoichiometry))
            reactants.append(srElement)

        e.append(reactants)

        products = eTree.Element('Products')
        for product, stoichiometry in R.products.items():
            srElement = eTree.Element('SpeciesReference')
            srElement.set('id', str(product.name))
            srElement.set('stoichiometry', str(stoichiometry))
            products.append(srElement)
        e.append(products)

        return e
