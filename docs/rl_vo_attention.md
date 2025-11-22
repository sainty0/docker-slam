# RL-VO Attention Encoder

The policy/value networks in `rl_vo/policies/attention_policy.py` consume observations that mix slow global stats with short windows of per-scan features. The encoder therefore splits the observation vector into fixed channels, a set of variable-length tokens, and a “critique tail” reserved for the value net. This document explains how the attention module maps that layout into actor/critic latents.

## Observation Layout Recap
- **Fixed block** (`agent_obs_dim_fixed = 16` by default): `[pts_per_scan_mean/std, scan_rate_hz, surf_pts_mean/std, corner_pts_mean/std, odom_rate_hz, pose_dropouts_s, vel_norm_mean/std, acc_jolt_mean, imu_ang_vel_rms, imu_lin_acc_rms, planarity_ratio_mean, action_last]`.
- **Variable tokens**: up to `tokens.max_tokens` sequences (default `64`) of length `tokens.variable_feature_dim` (default `3`). Metric exporter aligns `[surf_pts, corner_pts, vel_norm]` onto scan timestamps and zero-pads the remainder.
- **Critique tail** (`critique_dim = 4`): `[odom_rate_hz, pose_dropouts_s, scan_rate_hz, pts_per_scan_mean]`. Only the critic uses those extra scalars.

`RunningMeanStdLite` in `rl_vo/env/rl_env.py` normalises the concatenated vector before it reaches the policy.

## Encoder Building Blocks
### `PerceiverI`
```python
class PerceiverI(nn.Module):
    def __init__(self, kv_dim, num_queries, num_heads=4, dim_head=32)
```
- Flattens the variable tokens and projects them to `query_dim = num_heads * dim_head`.
- Maintains `num_queries` learnable latent vectors (`self.latents`).
- Runs PyTorch `nn.MultiheadAttention` (`batch_first=True`) where each latent attends over the encoded tokens. `key_padding_mask` masks padded rows (all-zero tokens) so the attention ignores them.
- Output shape: `(batch, num_queries, query_dim)`.

### `AttentionNetwork`
`AttentionNetwork` wraps the attention layer and two MLPs (one for the policy, one for the value function):
- `forward_variable()` reshapes the observation back into `[batch, max_tokens, variable_feature_dim]`, builds a binary `valid_mask` by checking whether all token features sum to zero, and invokes `PerceiverI`.
- Attended latents are flattened to `num_queries * num_heads * dim_head` (default `4 * 4 * 16 = 256`) and concatenated with the fixed stats.
- Policy head input size: `obs_dim_fixed + attn_dim` (default `16 + 256 = 272`).
- Value head input size adds `critique_dim` so the critic sees both the actor features and the tail (default `272 + 4 = 276`).
- Architecture comes from `policy_kwargs["net_arch"]`, typically `[256, 256]` per head with ReLU activations.

### `CustomActorCriticPolicy`
- Extends Stable-Baselines3 `ActorCriticPolicy`.
- Overrides `_build_mlp_extractor()` to instantiate `AttentionNetwork` using env-reported dims (`encoder_kwargs`).
- Keeps the standard SB3 `features_extractor` (flat pass-through) and `DiagGaussianDistribution` for actions, so the rest of PPO stays unchanged.

## Forward Pass Walkthrough
The relevant `AttentionNetwork.forward()` code can be summarised as:

```python
def forward(self, features):
    agent_features = features[:, :-self.critique_dim]
    agent_features = self.forward_variable(agent_features)
    critique_features = torch.cat([agent_features,
                                   features[:, -self.critique_dim:]], dim=1)
    return self.policy_net(agent_features), self.value_net(critique_features)
```

`forward_variable()` expands into:

1. `variable_features = features[:, self.obs_dim_fixed:]` and reshape to `[batch, max_tokens, variable_feature_dim]`.
2. `valid_mask = torch.abs(variable_features.sum([1, 2])) != 0` detects whether an environment in the batch has any non-zero token.
3. Initialise `out_attn_features = zeros(batch, attn_flat_dim)`.
4. For valid entries:
   - `key_padding_mask = torch.abs(variable_features.sum(-1)) == 0` marks padded token positions.
   - Run `self.variable_encoder(variable_features, key_padding_mask)` (multi-head attention).
   - Flatten to `[batch_valid, attn_flat_dim]` and scatter back into `out_attn_features`.
5. Concatenate `features[:, :self.obs_dim_fixed]` (fixed stats) with `out_attn_features`.

## Why Attention?
- Each MulRan scan can produce wildly different feature counts. MLPs over a flat fixed-size history would be dominated by padding. The Perceiver-style latent queries always operate on the subset of real tokens reported by the metrics exporter, letting the policy focus on relative surf/corner density and instantaneous velocity without guessing which portion of the flattened vector is valid.
- Multi-head attention (4 heads) captures correlations such as “surf points are high but odom velocity is low” versus “both are high”. Queries are learnable, so the encoder can dedicate a latent to trends (average over tokens) and another to outliers (recent spikes).
- The critic receives the same attended representation plus the extra context tail so it can focus on long-horizon stability (odom cadence, dropouts) while the actor emphasises reactive cues.

## Integration Summary
- **Policy path**: `CustomActorCriticPolicy.__call__` uses the attention-backed latent (`latent_dim_pi`) to parameterise a diagonal Gaussian over `[0,1]` actions (SB3 squashes/clips to env bounds).
- **Value path**: Receives `latent_dim_vf` with critique tail appended, resulting in more stable APE predictions even when some environments lack valid tokens.
- **Mask handling**: If the metrics exporter has not emitted any tokens yet (e.g., right after reset), the attention output is zero and the env marks the step invalid so PPO simply ignores it.

Refer to [rl_vo_overview.md](rl_vo_overview.md) for how these observations are produced, and to [rl_vo_ppo.md](rl_vo_ppo.md) for how the resulting latents feed into the PPO losses.
