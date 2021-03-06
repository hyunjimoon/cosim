"""Test the behaviour of the coupled HMC kernel"""

import jax
import jax.numpy as jnp
import jax.scipy.stats as stats
import numpy as np

import cosim.coupled.hmc as coupled_hmc
import cosim.hmc as hmc
from .utils import inference_loop



def normal_potential_fn(x):
    return -stats.norm.logpdf(x, loc=1.0, scale=2.0).squeeze()


def test_coupling_hmc():
    rng_key = jax.random.PRNGKey(19)
    n_sampling_steps = 50_000

    potential = lambda x: normal_potential_fn(**x)

    initial_position_1 = {"x": 1.}
    initial_position_2 = {"x": -1.}

    initial_state_hmc = hmc.new_state(initial_position_1, potential)
    initial_state_coupled_hmc = coupled_hmc.new_state(initial_position_1, initial_position_2, potential)

    parameters = {"step_size": 1e-2,
                  "inverse_mass_matrix": jnp.array([0.1]),
                  "num_integration_steps": 100,
                  }

    hmc_kernel = hmc.kernel(potential, **parameters)
    coupled_hmc_kernel = coupled_hmc.kernel(potential, **parameters)

    hmc_states = inference_loop(rng_key, hmc_kernel, initial_state_hmc, n_sampling_steps)
    coupled_hmc_states = inference_loop(rng_key, coupled_hmc_kernel, initial_state_coupled_hmc, n_sampling_steps)

    hmc_samples = hmc_states.position["x"]
    coupled_hmc_states_1 = coupled_hmc_states.state_1.position["x"]
    coupled_hmc_states_2 = coupled_hmc_states.state_2.position["x"]

    np.testing.assert_array_almost_equal(hmc_samples, coupled_hmc_states_1)
    np.testing.assert_array_almost_equal(coupled_hmc_states_1[2000:],
                                         coupled_hmc_states_2[2000:])  # the two trajectories match
    np.testing.assert_array_less(coupled_hmc_states_2[:1000], coupled_hmc_states_1[:1000])  # burn-in phase
