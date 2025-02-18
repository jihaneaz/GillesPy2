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

from gillespy2.solvers.cpp.c_decoder import BasicSimDecoder
from gillespy2.solvers.utilities import solverutils as cutils
from gillespy2.core import GillesPySolver, Model
from gillespy2.core.gillespyError import *
from gillespy2.core import Results

from .c_solver import CSolver, SimulationReturnCode

class ODECSolver(GillesPySolver, CSolver):
    name = "ODECSolver"
    target = "ode"

    def get_solver_settings(self):
        """
        :returns: Tuple of strings, denoting all keyword argument for this solvers run() method.
        """
        return ('model', 't', 'number_of_trajectories', 'timeout', 'increment', 'seed', 'debug', 'profile')

    def run(self=None, model: Model = None, t: int = 20, number_of_trajectories: int = 1, timeout: int = 0,
            increment: int = None, seed: int = None, debug: bool = False, profile: bool = False, variables={},
            resume=None, live_output: str = None, live_output_options: dict = {}, **kwargs):

        if self is None:
            self = ODECSolver(model, resume=resume)
        if self.model is None:
            if model is None:
                raise SimulationError("A model is required to run the simulation.")
            self._set_model(model=model)
        if model is not None and model.get_json_hash() != self.model.get_json_hash():
            raise SimulationError("Model must equal ODECSolver.model.")
        self.model.resolve_parameters()
        self.validate_sbml_features(model=model)

        increment = self.get_increment(increment=increment)

        # Validate parameters prior to running the model.
        self._validate_type(variables, dict, "'variables' argument must be a dictionary.")

        self._validate_resume(t, resume)
        self._validate_kwargs(**kwargs)

        if resume is not None:
            t = abs(t - int(resume["time"][-1]))

        number_timesteps = int(round(t / increment + 1))

        args = {
            "trajectories": number_of_trajectories,
            "timesteps": number_timesteps,
            "end": t,
            "increment": increment,
            "interval": str(number_timesteps),
        }

        if self.variable:
            populations = cutils.update_species_init_values(self.model.listOfSpecies, self.species, variables, resume)
            parameter_values = cutils.change_param_values(self.model.listOfParameters, self.parameters, self.model.volume, variables)

            args.update({
                "init_pop": populations,
                "parameters": parameter_values
            })

        seed = self._validate_seed(seed)
        if seed is not None:
            args.update({
                "seed": seed
            })

        if live_output is not None:
            live_output_options['type'] = live_output
            display_args = {
                "model": self.model, "number_of_trajectories": number_of_trajectories, "timeline": np.linspace(0, t, number_timesteps),
                "live_output_options": live_output_options, "resume": bool(resume)
            }
        else:
            display_args = None

        args = self._make_args(args)
        decoder = BasicSimDecoder.create_default(number_of_trajectories, number_timesteps, len(self.model.listOfSpecies))

        sim_exec = self._build(self.model, self.target, self.variable, False)
        sim_status = self._run(sim_exec, args, decoder, timeout, display_args)

        if sim_status == SimulationReturnCode.FAILED:
            raise gillespyError.ExecutionError("Error encountered while running simulation C++ file:\n"
                f"Return code: {int(sim_status)}.\n")

        trajectories, time_stopped = decoder.get_output()

        simulation_data = self._format_output(trajectories)
        if sim_status == SimulationReturnCode.PAUSED:
            simulation_data = self._make_resume_data(time_stopped, simulation_data, t)
        if resume is not None:
            simulation_data = self._update_resume_data(resume, simulation_data, time_stopped)
        self.result = simulation_data
        self.rc = int(sim_status)

        return Results.build_from_solver_results(self, live_output_options)