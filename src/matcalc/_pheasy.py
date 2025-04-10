"""Calculator for force constants extraction, """
"""using finite difference method, MD trejectories,""" 
"""Compressive Sensing technique."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import phonopy
from phonopy.file_IO import write_FORCE_CONSTANTS as write_force_constants
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.phonopy import get_phonopy_structure, get_pmg_structure

from ._base import PropCalc
from ._relaxation import RelaxCalc

from phonopy.interface.vasp import write_vasp
import numpy as np
import pickle


if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from ase.calculators.calculator import Calculator
    from numpy.typing import ArrayLike
    from phonopy.structure.atoms import PhonopyAtoms
    from pymatgen.core import Structure


@dataclass
class PhononCalc(PropCalc):
    """
    PhononCalc is a specialized class for calculating thermal properties of structures
    using phonopy. It extends the functionalities of base property calculation classes
    and integrates phonopy for phonon-related computations.

    The class is designed to work with a provided calculator and a structure, enabling
    the computation of various thermal properties such as free energy, entropy,
    and heat capacity as functions of temperature. It supports relaxation of the
    structure, control over displacement magnitudes, and customization of output
    file paths for storing intermediate and final results.

    :ivar calculator: Calculator object to perform energy and force evaluations.
    :type calculator: Calculator
    :ivar atom_disp: Magnitude of atomic displacement for phonon calculations.
    :type atom_disp: float
    :ivar supercell_matrix: Matrix defining the supercell size for phonon calculations.
    :type supercell_matrix: ArrayLike
    :ivar t_step: Temperature step size in Kelvin for thermal property calculations.
    :type t_step: float
    :ivar t_max: Maximum temperature in Kelvin for thermal property calculations.
    :type t_max: float
    :ivar t_min: Minimum temperature in Kelvin for thermal property calculations.
    :type t_min: float
    :ivar fmax: Maximum force tolerance for structure relaxation.
    :type fmax: float
    :ivar optimizer: Optimizer to be used for structure relaxation.
    :type optimizer: str
    :ivar relax_structure: Flag to indicate whether the structure should be relaxed
        before phonon calculations.
    :type relax_structure: bool
    :ivar relax_calc_kwargs: Additional keyword arguments for structure relaxation calculations.
    :type relax_calc_kwargs: dict | None
    :ivar write_force_constants: Path or boolean flag indicating where to save the
        calculated force constants.
    :type write_force_constants: bool | str | Path
    :ivar write_band_structure: Path or boolean flag indicating where to save the
        calculated phonon band structure.
    :type write_band_structure: bool | str | Path
    :ivar write_total_dos: Path or boolean flag indicating where to save the total
        density of states (DOS) data.
    :type write_total_dos: bool | str | Path
    :ivar write_phonon: Path or boolean flag indicating where to save the full
        phonon data.
    :type write_phonon: bool | str | Path
    """

    calculator: Calculator
    atom_disp: float = 0.015
    supercell_matrix: ArrayLike = ((2, 0, 0), (0, 2, 0), (0, 0, 2))
    t_step: float = 10
    t_max: float = 1000
    t_min: float = 0
    fmax: float = 0.1
    optimizer: str = "FIRE"
    relax_structure: bool = True
    relax_calc_kwargs: dict | None = None
    write_force_constants: bool | str | Path = False
    write_band_structure: bool | str | Path = False
    write_total_dos: bool | str | Path = False
    write_phonon: bool | str | Path = True

    # set up a variable to select the fitting method, like fd, lasso, md terejectory for pheasy
    fitting_method: str = "LASSO"
    num_snapshots: int = 10

    def __post_init__(self) -> None:
        """Set default paths for where to save output files."""
        # map True to canonical default path, False to "" and Path to str
        for key, val, default_path in (
            ("write_force_constants", self.write_force_constants, "force_constants"),
            ("write_band_structure", self.write_band_structure, "band_structure.yaml"),
            ("write_total_dos", self.write_total_dos, "total_dos.dat"),
            ("write_phonon", self.write_phonon, "phonon.yaml"),
        ):
            setattr(self, key, str({True: default_path, False: ""}.get(val, val)))  # type: ignore[arg-type]

    def calc(self, structure: Structure | dict[str, Any]) -> dict:
        """Calculates thermal properties of Pymatgen structure with phonopy.

        Args:
            structure: Pymatgen structure.

        Returns:
        {
            phonon: Phonopy object with force constants produced
            thermal_properties:
                {
                    temperatures: list of temperatures in Kelvin,
                    free_energy: list of Helmholtz free energies at corresponding temperatures in kJ/mol,
                    entropy: list of entropies at corresponding temperatures in J/K/mol,
                    heat_capacity: list of heat capacities at constant volume at corresponding temperatures in J/K/mol,
                    The units are originally documented in phonopy.
                    See phonopy.Phonopy.run_thermal_properties()
                    (https://github.com/phonopy/phonopy/blob/develop/phonopy/api_phonopy.py#L2591)
                    -> phonopy.phonon.thermal_properties.ThermalProperties.run()
                    (https://github.com/phonopy/phonopy/blob/develop/phonopy/phonon/thermal_properties.py#L498)
                    -> phonopy.phonon.thermal_properties.ThermalPropertiesBase.run_free_energy()
                    (https://github.com/phonopy/phonopy/blob/develop/phonopy/phonon/thermal_properties.py#L217)
                    phonopy.phonon.thermal_properties.ThermalPropertiesBase.run_entropy()
                    (https://github.com/phonopy/phonopy/blob/develop/phonopy/phonon/thermal_properties.py#L233)
                    phonopy.phonon.thermal_properties.ThermalPropertiesBase.run_heat_capacity()
                    (https://github.com/phonopy/phonopy/blob/develop/phonopy/phonon/thermal_properties.py#L225)
                }
        }
        """
        result = super().calc(structure)
        structure_in: Structure = result["final_structure"]

        if self.relax_structure:
            relaxer = RelaxCalc(
                self.calculator, fmax=self.fmax, optimizer=self.optimizer, **(self.relax_calc_kwargs or {})
            )
            result |= relaxer.calc(structure_in)
            structure_in = result["final_structure"]
        cell = get_phonopy_structure(structure_in)
        phonon = phonopy.Phonopy(cell, self.supercell_matrix)  # type: ignore[arg-type]

        if self.fitting_method == "FDM":
            phonon.generate_displacements(distance=self.atom_disp)
        
        elif self.fitting_method == "LASSO":
            phonon.generate_displacements(distance=self.atom_disp, number_of_snapshots=self.num_snapshots, random_seed=42)
        
        elif self.fitting_method == "MD":
            #pass
            #phonon.generate_displacements(distance=self.atom_disp, number_of_snapshots=self.num_snapshots)
            print("MD fitting method is not implemented yet.")

        else:
            raise ValueError(f"Unknown fitting method: {self.fitting_method}")

            
        disp_supercells = phonon.supercells_with_displacements
        # to get a better result, I suggest to deduct the forces from the supercell
        disp_supercells = disp_supercells.append(phonon.supercell)  # type:ignore[union-attr]

        phonon.forces = [  # type: ignore[assignment]
            _calc_forces(self.calculator, supercell)
            for supercell in disp_supercells  # type:ignore[union-attr]
            if supercell is not None
        ]

        # Write the POSCAR and SPOSCAR files for the input of pheasy code
        supercell = phonon.get_supercell()
        write_vasp("POSCAR", cell)
        write_vasp("SPOSCAR", supercell)

        # get the force-displacement dataset from previous calculations
        dataset_forces = [np.array(forces) for forces in displacement_data["forces"]]
        dataset_forces_array = np.array(dataset_forces)

        # To deduct the residual forces on an equilibrium structure to eliminate the
        # fitting error
        dataset_forces_array_rr = dataset_forces_array - dataset_forces_array[-1, :, :]

        # force matrix on the displaced structures
        dataset_forces_array_disp = dataset_forces_array_rr[:-1, :, :]
        dataset_disps = [
            np.array(disps.cart_coords)
            for disps in displacement_data["displaced_structures"]
        ]

        # get the displacement dataset
        dataset_disps_array_rr = np.round(
            (dataset_disps - supercell.get_positions()), decimals=16
        ).astype('double')
        dataset_disps_array_use = dataset_disps_array_rr[:-1, :, :]

        # get the number of displacements for harmonic phonon calculation
        num_har = dataset_disps_array_use.shape[0]

        # save the displacement and force matrix in the current directory
        # for the future use by pheasy code
        with open("disp_matrix.pkl", "wb") as file:
            pickle.dump(dataset_disps_array_use, file)
        with open("force_matrix.pkl", "wb") as file:
            pickle.dump(dataset_forces_array_disp, file)
        
        










        
        # To deduct the forces from the supercell for all the displacements
        phonon.forces = phonon.forces - phonon.forces[-1]
        # get the forces for rest of displacements
        phonon.forces = phonon.forces[:-1]
        







        phonon.produce_force_constants()
        phonon.run_mesh()
        phonon.run_thermal_properties(t_step=self.t_step, t_max=self.t_max, t_min=self.t_min)
        if self.write_force_constants:
            write_force_constants(phonon.force_constants, filename=self.write_force_constants)
        if self.write_band_structure:
            phonon.auto_band_structure(write_yaml=True, filename=self.write_band_structure)
        if self.write_total_dos:
            phonon.auto_total_dos(write_dat=True, filename=self.write_total_dos)
        if self.write_phonon:
            phonon.save(filename=self.write_phonon)
        return result | {"phonon": phonon, "thermal_properties": phonon.get_thermal_properties_dict()}


def _calc_forces(calculator: Calculator, supercell: PhonopyAtoms) -> ArrayLike:
    """Helper to compute forces on a structure.

    Args:
        calculator: ASE Calculator
        supercell: Supercell from phonopy.

    Return:
        forces
    """
    struct = get_pmg_structure(supercell)
    atoms = AseAtomsAdaptor.get_atoms(struct)
    atoms.calc = calculator
    return atoms.get_forces()


