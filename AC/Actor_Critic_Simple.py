import os

import dill
import gymnasium as gym
import haiku as hk
import jax.nn as nn
import jax.random as random
import numpy as np
import optax
from jax import grad, jit, tree_map
from tqdm import tqdm

from AC.model import policy_fn, val_fn
from AC.plot_utils import plot_return, plot_tde

dir_path = os.path.dirname(os.path.realpath(__file__))
gamma = 0.95
alpha_critic = 3e-4
alpha_actor = 2e-4
episodes = 100
num_runs = 3
env = gym.make('LunarLander-v2')


actor = hk.without_apply_rng(hk.transform(policy_fn))
critic = hk.without_apply_rng(hk.transform(val_fn))
predict = jit(critic.apply)


def value_loss(params, obs, G):
    value = critic.apply(params, obs)[0]
    tde = G - value
    return tde**2, tde


value_loss_grad_and_tde = jit(grad(value_loss, has_aux=True))


def log_prob_action(params, obs, rng_key):
    logits = actor.apply(params, obs)
    a = random.categorical(rng_key, logits)
    log_prob = nn.log_softmax(logits)
    return -log_prob[a], a


log_prob_grad_and_action = jit(grad(log_prob_action, has_aux=True))

actor_opt = optax.adam(alpha_actor)
critic_opt = optax.adam(alpha_critic)


@jit
def update_critic(params, opt_state, grad):
    updates, new_opt_state = critic_opt.update(grad, opt_state)
    new_params = optax.apply_updates(params, updates)
    return new_params, new_opt_state


@jit
def update_actor(params, opt_state, grad):
    updates, new_opt_state = actor_opt.update(grad, opt_state)
    new_params = optax.apply_updates(params, updates)
    return new_params, new_opt_state


runs = []
tde_over_runs = []
for run in tqdm(range(num_runs)):
    # random seeding
    rng = hk.PRNGSequence(run)

    # initialization
    obs, info = env.reset(seed=run)
    actor_params = actor.init(rng.next(), obs)
    critic_params = critic.init(rng.next(), obs)
    actor_opt_state = actor_opt.init(actor_params)
    critic_opt_state = critic_opt.init(critic_params)
    returns = []
    tdes = []

    for eps in range(episodes):
        terminated = False
        truncated = False
        I = 1.0
        eps_return = 0.0
        total_tde = 0.0
        while not terminated and not truncated:
            log_prob_grad, a = log_prob_grad_and_action(actor_params,
                                                        obs,
                                                        rng.next())
            next_obs, reward, terminated, truncated, info = env.step(a.item())

            eps_return += reward*I

            if terminated:
                G = reward
            else:
                G = reward + gamma*predict(critic_params, next_obs)[0]

            value_loss_grad, tde = value_loss_grad_and_tde(critic_params,
                                                           obs,
                                                           G)
            total_tde += abs(tde.item())
            action_loss_grad = tree_map(lambda g: I*tde*g,
                                        log_prob_grad)

            critic_params, critic_opt_state = update_critic(critic_params,
                                                            critic_opt_state,
                                                            value_loss_grad)
            actor_params, actor_opt_state = update_actor(actor_params,
                                                         actor_opt_state,
                                                         action_loss_grad)
            obs = next_obs
            I = gamma * I
        obs, info = env.reset()
        returns.append(eps_return)
        tdes.append(total_tde)

    runs.append(returns)
    tde_over_runs.append(tdes)
    with open(os.path.join(dir_path, 'weights', f'critic_params_{run}.pickle'), 'wb') as f:
        dill.dump(critic_params, f)
    with open(os.path.join(dir_path, 'weights', f'actor_params_{run}.pickle'), 'wb') as f:
        dill.dump(actor_params, f)

env.close()

runs = np.array(runs)
runs_mean = np.mean(runs, axis=0)
runs_std = np.std(runs, axis=0)
plot_return(runs_mean, runs_std, episodes, dir_path)

tdes_over_runs = np.array(tde_over_runs)
tdes_mean = np.mean(tdes_over_runs, axis=0)
tdes_std = np.std(tdes_over_runs, axis=0)
plot_tde(tdes_mean, tdes_std, episodes, dir_path)