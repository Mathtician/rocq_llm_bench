# Configs kept for provenance (results reference them by name) but not used in new runs.

- pi-baseten-*: Baseten rate-limits sustained throughput (429 after a few minutes even at one job), so
  a Putnam-length attempt cannot complete there. Its short-problem results stand.
- pi-deepseek-v41-flash: DeepSeek's first-party API serves V4.1 Flash only as `deepseek-flash`, a
  moving alias, so the config cannot keep naming the same model. Replaced by
  pi-fireworks-deepseek-v41-flash (versioned id). Its results (deepseek-v41-flash-sweep-1) stand.
