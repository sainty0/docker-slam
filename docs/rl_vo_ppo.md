# RL-VO PPO Implementation

`rl_vo/rl_algorithms/ppo.py` contains the PPO variant that trains the attention-based actor/critic in `rl_vo/policies/attention_policy.py`. It reuses the Stable-Baselines3 API but replaces the rollout buffer, adds WANDB hooks, and exposes SC-LIO-SAM aware evaluation routines.

## Policy and Value Networks
- **Policy class**: `CustomActorCriticPolicy` inherits from SB3’s `ActorCriticPolicy`. `AttentionNetwork` (see [rl_vo_attention.md](rl_vo_attention.md)) acts as the `mlp_extractor`, feeding separate MLPs for actor (`latent_dim_pi`) and critic (`latent_dim_vf`).
- **Distribution**: Actions live in a 1-D `spaces.Box([0.0], [1.0])`. SB3’s `DiagGaussianDistribution` parameterises an unconstrained Gaussian whose outputs are clipped to `[0,1]` before being log-scaled to meters (`action_to_leaf()` in `rl_vo/env/rl_env.py`).
- **Shared preprocessing**: Observations are already normalised inside the env via `RunningMeanStdLite`, so PPO receives zero-mean, unit-variance features each step.

## Loss Terms (see `PPO.train`)
| Term | Code location | Description |
| --- | --- | --- |
| Policy loss | `policy_loss = -th.min(policy_loss_1, policy_loss_2).mean()` | Clipped surrogate objective with `clip_range=0.2`. |
| Value loss | `F.mse_loss(rollout_data.returns, values_pred)` | Uses TD(λ) returns from the masked buffer; optional value clipping disabled by default. |
| Entropy bonus | `entropy_loss = -th.mean(entropy)` | Weighted by `ent_coef`. Keeps exploration alive while SC-LIO-SAM replays varied scenes. |
| Gradient clip | `th.nn.utils.clip_grad_norm_(…, max_grad_norm)` | Prevents large updates when rewards spike (e.g., after a sudden drift correction). |
| Approx KL | `approx_kl_div = mean((exp(log_ratio) - 1) - log_ratio)` | Monitored to detect destabilising updates; target KL is unset so no automatic early stop. |

Losses are logged to WANDB every optimizer step. `get_linear_fn(3e-4, 3e-5, 1.0)` schedules the learning rate from 3e-4 down to 3e-5 over the full training horizon.

## Trajectory Collection and Advantage Estimation
- `OnPolicyAlgorithm.collect_rollouts()` drives the ROS-backed env until `n_steps` per environment are gathered. Each `env.step()` returns an additional `valid_mask` array.
- `MaskedRolloutBuffer.add()` stores `(obs, action, reward, episode_start, value, log_prob, valid_mask)` for every env/time pair. Invalid stages (no GT or metrics) keep their entries but are marked so they never participate in sampling.
- `MaskedRolloutBuffer.compute_returns_and_advantage()` runs Generalised Advantage Estimation with a twist:
  - Temporal discount becomes `valid_mask * gamma + (1 - valid_mask)`, so when a step is invalid the bootstrap degenerates to identity and the transition contributes zero advantage.
  - `returns = advantages + values` exactly as in vanilla PPO.
- `MaskedRolloutBuffer.get(batch_size)` flattens time/env dimensions, filters indices where `valid_mask` is `True`, randomises the order, and yields batches sized to `batch_size`. This keeps PPO on-policy (rollouts flushed every update) while discarding ROS artefacts.

## Training Loop in Context
1. `train.py` instantiates `PPO(policy=CustomActorCriticPolicy, env=RLBatchedEnv, …)`.
2. `model.learn(total_timesteps)` (implemented in `OnPolicyAlgorithm.learn`) repeatedly:
   - Calls `collect_rollouts()` to fill the buffer and update `self.num_timesteps`.
   - Every 10 iterations copies the observation RMS to the validation env so evaluations see the same normalisation.
   - Invokes `PPO.train()` for `n_epochs` passes over the masked buffer.
   - Optionally evaluates via `evaluation_epoch_sclsam()` which runs deterministic single-step episodes and logs APE, timeout rate, etc.
3. Checkpoints consisting of `policy.save()` and `env.save_rms()` land under `logs/<timestamp>/Policy/iter_XXXXX.pth` when `eval_interval` divides the iteration count.

## Default Hyperparameters (from `rl_vo/config/config.yaml`)
| Name | Meaning | Default |
| --- | --- | --- |
| `agent.n_steps` | Rollout length per env | 128 |
| `agent.batch_size` | Minibatch size inside PPO | 64 |
| `agent.gamma` | Discount factor | 0.99 |
| `agent.gae_lambda` | GAE smoothing | 0.95 |
| `agent.n_epochs` | Policy/value passes per batch | 10 |
| `agent.ent_coef` | Entropy regularisation | 0.01 |
| `agent.vf_coef` | Value loss weight | 0.5 |
| `agent.max_grad_norm` | Gradient clip | 0.5 |
| `agent.use_sde` | State-dependent exploration | `false` (Gaussian noise only) |
| `learning_rate` | Schedule passed via `get_linear_fn` | 3e-4 → 3e-5 |
| `clip_range` | PPO clip parameter (`PPO.__init__`) | 0.2 |

These values were chosen to balance on-policy stability with the slow, expensive nature of SC-LIO-SAM rollouts: `n_steps=128` keeps buffer sizes manageable and aligns with ~2 minutes of lidar replay at 1 Hz in DRY_RUN mode; `batch_size=64` divides evenly into valid transitions after masking.

## Robotics-Specific Considerations
- **Valid-mask filtering** eliminates steps captured while ROS is still spinning up, preventing PPO from fitting on zero observations or zero rewards.
- **Action scaling** keeps the raw PPO outputs nicely conditioned; the log-space conversion happens entirely inside the env so PPO still optimises over `[0,1]`.
- **Reward sparsity**: APE can be zero when GT is missing, so the buffer simply refuses to use those steps. Combined with `gae_lambda=0.95`, advantages propagate mainly across contiguous, valid windows, matching how SC-LIO-SAM drifts gradually rather than instantaneously.
- **Eval integration**: `evaluation_epoch_sclsam()` runs deterministic forward passes, clips actions to env bounds, and logs APE/timeouts to WANDB so you can compare policies without re-running full PPO training.

For the complementary pieces, see [rl_vo_buffer.md](rl_vo_buffer.md) for buffer semantics and [rl_vo_training_loop.md](rl_vo_training_loop.md) for the ROS-driven rollout lifecycle.
