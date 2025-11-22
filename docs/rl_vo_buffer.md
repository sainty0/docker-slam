# RL-VO Rollout Buffer

`rl_vo/rl_algorithms/buffers.py` defines `MaskedRolloutBuffer`, the trajectory store used by PPO. It is SB3-compatible but extended so the ROS environment can mark steps as invalid whenever SC-LIO-SAM metrics or GT are missing. This document clarifies the storage layout and how transitions flow from the environment to PPO.

## Stored Fields
For buffer size `n_steps` and `n_envs` parallel environments, the buffer owns:
- `observations[step, env, obs_dim]`
- `actions[step, env, action_dim]`
- `rewards[step, env]`
- `valid_mask[step, env]` — `True` only when `RLBatchedEnv.step()` succeeded in producing metrics, GT, and a reward derived from APE.
- `episode_starts[step, env]` — the standard SB3 flag for resets.
- `values[step, env]` — critic predictions stored before bootstrapping.
- `log_probs[step, env]` — log π(a|s) before updates.
- `advantages[step, env]`, `returns[step, env]` — filled during `compute_returns_and_advantage`.

Arrays are initialised in `MaskedRolloutBuffer.reset()` and reside on CPU (`np.float32`) until sampling, where they turn into PyTorch tensors via `to_torch`.

## Interaction with `RLBatchedEnv`
1. `OnPolicyAlgorithm.collect_rollouts()` calls `env.step(clipped_actions, use_gt_initialization=True)` once per timestep.
2. `RLBatchedEnv.step()`:
   - Publishes the PPO action to `/lio_sam/params/mapping_surf_leaf_size` (unless in DRY_RUN).
   - Advances SC-LIO-SAM for `step_len_s`, triggers `/rl_metrics/commit`, and attempts to compute rolling APE vs MulRan GT.
   - Builds the next observation via `_obs_from_stats()` and sets `valid_mask = [True]` only if metrics and GT exist. When MulRan playback hits EOF or ROS drops, `valid_mask = [False]` and the episode immediately restarts.
3. `collect_rollouts()` receives `(obs, reward, done, info, valid_mask)` and calls `rollout_buffer.add(..., valid_mask)`.

## Advantage Computation with Masks
`compute_returns_and_advantage(last_values, dones, last_valid_step)` differs from SB3’s default in two ways:
- `temporal_discount = valid_mask[step] * gamma + (1 - valid_mask[step])`. For invalid steps `temporal_discount` becomes `1.0`, meaning the TD error collapses to `reward - value` and the subsequent advantage accumulation is halted.
- The final call `rollout_buffer.compute_returns_and_advantage(..., last_valid_step=valid_mask)` ensures the mask from the very last env step is honoured while bootstrapping from `last_values`.

The upshot: invalid transitions can exist inside the buffer (to keep shapes consistent) but never influence PPO, because their advantages and returns are zeroed and they are excluded from minibatches.

## Sampling
When `PPO.train()` iterates over the buffer:
1. `MaskedRolloutBuffer.get(batch_size)` flattens the buffer to shape `(n_steps * n_envs, …)`.
2. `indices = indices[self.swap_and_flatten(valid_mask).squeeze(1)]` filters indices to only the valid entries.
3. The indices are shuffled and chunked into minibatches. Each minibatch yields a `RolloutBufferSamples` tuple of PyTorch tensors ready for the loss computation.

This design preserves PPO’s on-policy guarantees while coping with ROS realities such as:
- Metrics exporter not yet warmed up after a reset.
- GT files temporarily missing (env falls back to `est.tum` and refuses to score that step).
- rosbridge hiccups or `file_player` pausing, which would otherwise insert pathological zero observations.

## Step-by-Step: From Environment Step to PPO Update
1. **Environment step**:
   - Policy emits an action; env log-scales it to `leaf` and runs ROS for one `step_len_s`.
   - Env computes reward + `valid_mask` and returns the next observation.
2. **Buffer append**:
   - `rollout_buffer.add()` stores tensors/arrays and increments `self.pos`. Once `pos == buffer_size`, `.full = True`.
3. **Rollout end**:
   - `collect_rollouts()` queries the critic for `last_values` on the most recent observation.
   - `compute_returns_and_advantage()` processes the whole buffer with masks.
4. **Training**:
   - `PPO.train()` loops `n_epochs` times; each epoch shuffles the valid indices and feeds batches into the loss.
   - After training, `rollout_buffer.reset()` clears arrays for the next collection phase.

Because the buffer flushes after every PPO update, the algorithm remains strictly on-policy even though ROS introduces asynchronous delays. See [rl_vo_ppo.md](rl_vo_ppo.md) for how these samples feed into the PPO losses, and [rl_vo_training_loop.md](rl_vo_training_loop.md) for the broader orchestration.
