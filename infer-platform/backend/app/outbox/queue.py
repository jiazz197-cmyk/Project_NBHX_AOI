"""outbox 队列：入队 / 重试 / 幂等。

跨平台回传以 (station_code, seq) 去重；断网时积压，恢复后补传。
对齐 docs/contracts/跨平台契约_A-B.md。

TODO: 实现 outbox 队列。
"""
