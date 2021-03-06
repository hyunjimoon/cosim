"""Public API for the HMC Kernel"""
from functools import partial
from typing import Callable, Dict, List, NamedTuple, Tuple, Union

import jax.numpy as jnp
import numpy as np

import cosim.inference.base as base
import cosim.inference.integrators as integrators
import cosim.inference.metrics as metrics
import cosim.inference.proposal as proposal
import cosim.inference.trajectory as trajectory

Array = Union[np.ndarray, jnp.DeviceArray]
PyTree = Union[Dict, List, Tuple]

__all__ = ["new_state", "kernel"]


class HMCInfo(NamedTuple):
    """Additional information on the HMC transition.

    This additional information can be used for debugging or computing
    diagnostics.

    momentum:
        The momentum that was sampled and used to integrate the trajectory.
    acceptance_probability
        The acceptance probability of the transition, linked to the energy
        difference between the original and the proposed states.
    is_accepted
        Whether the proposed position was accepted or the original position
        was returned.
    is_divergent
        Whether the difference in energy between the original and the new state
        exceeded the divergence threshold.
    energy:
        Energy of the transition.
    proposal
        The state proposed by the proposal. Typically includes the position and
        momentum.
    step_size
        Size of the integration step.
    num_integration_steps
        Number of times we run the symplectic integrator to build the trajectory
    """

    momentum: PyTree
    acceptance_probability: float
    is_accepted: bool
    is_divergent: bool
    energy: float
    proposal: integrators.IntegratorState
    num_integration_steps: int


new_state = base.new_hmc_state


def kernel(
        potential_fn: Callable,
        step_size: float,
        inverse_mass_matrix: Array,
        num_integration_steps: int,
        *,
        integrator: Callable = integrators.velocity_verlet,
        divergence_threshold: int = 1000,
):
    """Build a HMC kernel.

    Parameters
    ----------
    potential_fn
        A function that returns the potential energy of a chain at a given position.
    parameters
        A NamedTuple that contains the parameters of the kernel to be built.

    Returns
    -------
    A kernel that takes a rng_key and a Pytree that contains the current state
    of the chain and that returns a new state of the chain along with
    information about the transition.

    """
    momentum_generator, kinetic_energy_fn, _ = metrics.gaussian_euclidean(
        inverse_mass_matrix
    )
    symplectic_integrator = integrator(potential_fn, kinetic_energy_fn)
    proposal_generator = hmc_proposal(
        symplectic_integrator,
        kinetic_energy_fn,
        step_size,
        num_integration_steps,
        divergence_threshold,
    )
    kernel = base.hmc(momentum_generator, proposal_generator)
    return kernel


def hmc_proposal(
        integrator: Callable,
        kinetic_energy: Callable,
        step_size: float,
        num_integration_steps: int = 1,
        divergence_threshold: float = 1000,
) -> Callable:
    """Vanilla HMC algorithm.

    The algorithm integrates the trajectory applying a symplectic integrator
    `num_integration_steps` times in one direction to get a proposal and uses a
    Metropolis-Hastings acceptance step to either reject or accept this
    proposal. This is what people usually refer to when they talk about "the
    HMC algorithm".

    Parameters
    ----------
    integrator
        Symplectic integrator used to build the trajectory step by step.
    kinetic_energy
        Function that computes the kinetic energy.
    step_size
        Size of the integration step.
    num_integration_steps
        Number of times we run the symplectic integrator to build the trajectory
    divergence_threshold
        Threshold above which we say that there is a divergence.

    Returns
    -------
    A kernel that generates a new chain state and information about the transition.

    """
    build_trajectory = trajectory.static_integration(
        integrator, step_size, num_integration_steps
    )
    init_proposal, generate_proposal = proposal.proposal_generator(
        kinetic_energy, divergence_threshold
    )
    sample_proposal = proposal.static_binomial_sampling

    return partial(generate,
                   build_trajectory=build_trajectory,
                   init_proposal=init_proposal,
                   generate_proposal=generate_proposal,
                   sample_proposal=sample_proposal,
                   num_integration_steps=num_integration_steps)


def generate(
        rng_key,
        state: integrators.IntegratorState,
        build_trajectory: Callable,
        init_proposal: Callable,
        generate_proposal: Callable,
        sample_proposal: Callable,
        num_integration_steps: int
) -> Tuple[integrators.IntegratorState, HMCInfo]:
    """Generate a new chain state."""
    end_state = build_trajectory(state)
    end_state = integrators.flip_momentum(end_state)
    proposal = init_proposal(state)
    new_proposal, is_diverging = generate_proposal(proposal.energy, end_state)
    sampled_proposal, *info = sample_proposal(rng_key, proposal, new_proposal)
    do_accept, p_accept = info

    info = HMCInfo(
        state.momentum,
        p_accept,
        do_accept,
        is_diverging,
        new_proposal.energy,
        new_proposal,
        num_integration_steps,
    )

    return sampled_proposal.state, info
