# 舊寫法（7144b485）加壓 32 次

條件：`docker run --cpus=2 --memory=6g`，容器內 8 支 `python -c "while 1: pass"` 燒 CPU，`xargs -P 4` 並行，只跑 `test_what_the_2300_trigger_runs_after_the_2130_run[stuck]`（[`loop.sh`](loop.sh) `32 8 4`）。

## 每次的結束碼

```
old run=1 exit=1 seconds=65 serve end job=daily pid=53 exit=1 seconds=5
old run=2 exit=1 seconds=67 serve end job=daily pid=57 exit=1 seconds=5
old run=3 exit=1 seconds=64 serve end job=daily pid=52 exit=1 seconds=5
old run=4 exit=1 seconds=68 serve end job=daily pid=49 exit=1 seconds=5
old run=5 exit=1 seconds=67 serve end job=daily pid=137 exit=1 seconds=5
old run=6 exit=1 seconds=66 serve end job=daily pid=134 exit=1 seconds=5
old run=7 exit=1 seconds=68 serve end job=daily pid=148 exit=1 seconds=5
old run=8 exit=1 seconds=65 serve end job=daily pid=151 exit=1 seconds=5
old run=9 exit=1 seconds=67 serve end job=daily pid=226 exit=1 seconds=5
old run=10 exit=1 seconds=65 serve end job=daily pid=229 exit=1 seconds=5
old run=11 exit=1 seconds=70 serve end job=daily pid=236 exit=1 seconds=5
old run=12 exit=1 seconds=68 serve end job=daily pid=243 exit=1 seconds=5
old run=13 exit=1 seconds=69 serve end job=daily pid=321 exit=1 seconds=5
old run=14 exit=1 seconds=67 serve end job=daily pid=318 exit=1 seconds=5
old run=15 exit=1 seconds=68 serve end job=daily pid=335 exit=1 seconds=5
old run=16 exit=1 seconds=70 serve end job=daily pid=341 exit=1 seconds=5
old run=17 exit=1 seconds=69 serve end job=daily pid=407 exit=1 seconds=5
old run=18 exit=1 seconds=67 serve end job=daily pid=413 exit=1 seconds=5
old run=19 exit=1 seconds=68 serve end job=daily pid=424 exit=1 seconds=5
old run=20 exit=1 seconds=68 serve end job=daily pid=440 exit=1 seconds=5
old run=21 exit=1 seconds=65 serve end job=daily pid=499 exit=1 seconds=5
old run=22 exit=1 seconds=68 serve end job=daily pid=505 exit=1 seconds=5
old run=23 exit=1 seconds=67 serve end job=daily pid=516 exit=1 seconds=5
old run=24 exit=1 seconds=68 serve end job=daily pid=532 exit=1 seconds=5
old run=25 exit=1 seconds=68 serve end job=daily pid=591 exit=1 seconds=5
old run=26 exit=1 seconds=66 serve end job=daily pid=598 exit=1 seconds=5
old run=27 exit=1 seconds=65 serve end job=daily pid=611 exit=1 seconds=5
old run=28 exit=1 seconds=66 serve end job=daily pid=625 exit=1 seconds=5
old run=29 exit=1 seconds=67 serve end job=daily pid=687 exit=1 seconds=5
old run=30 exit=1 seconds=64 serve end job=daily pid=689 exit=1 seconds=5
old run=31 exit=1 seconds=65 serve end job=daily pid=700 exit=1 seconds=5
old run=32 exit=1 seconds=63 serve end job=daily pid=718 exit=1 seconds=5
```

## 每次輸出：錯誤行（若有）與最後 5 行

### run 1

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:19.795762+08:00 serve end job=daily pid=83 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.21s
```

### run 2

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.045716+08:00 serve end job=daily pid=85 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.80s
```

### run 3

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:19.642557+08:00 serve end job=daily pid=81 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 55.91s
```

### run 4

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:23.197775+08:00 serve end job=daily pid=79 exit=0 seconds=23
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.41s
```

### run 5

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.291657+08:00 serve end job=daily pid=166 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.90s
```

### run 6

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.549324+08:00 serve end job=daily pid=163 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.68s
```

### run 7

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.545173+08:00 serve end job=daily pid=177 exit=0 seconds=23
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.40s
```

### run 8

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.295340+08:00 serve end job=daily pid=179 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.00s
```

### run 9

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.190241+08:00 serve end job=daily pid=255 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.39s
```

### run 10

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:19.944995+08:00 serve end job=daily pid=260 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.00s
```

### run 11

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:24.494495+08:00 serve end job=daily pid=268 exit=0 seconds=24
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 61.29s (0:01:01)
```

### run 12

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.448191+08:00 serve end job=daily pid=271 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.30s
```

### run 13

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.146976+08:00 serve end job=daily pid=348 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 60.31s (0:01:00)
```

### run 14

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.190335+08:00 serve end job=daily pid=344 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.10s
```

### run 15

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.752486+08:00 serve end job=daily pid=360 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.91s
```

### run 16

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:23.152001+08:00 serve end job=daily pid=363 exit=0 seconds=23
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 61.39s (0:01:01)
```

### run 17

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.290317+08:00 serve end job=daily pid=430 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 60.29s (0:01:00)
```

### run 18

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.154982+08:00 serve end job=daily pid=438 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.30s
```

### run 19

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.649006+08:00 serve end job=daily pid=450 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.81s
```

### run 20

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.144021+08:00 serve end job=daily pid=457 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.99s
```

### run 21

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:19.953219+08:00 serve end job=daily pid=519 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.91s
```

### run 22

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.794424+08:00 serve end job=daily pid=530 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.31s
```

### run 23

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.790024+08:00 serve end job=daily pid=541 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.70s
```

### run 24

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.794636+08:00 serve end job=daily pid=549 exit=0 seconds=22
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.50s
```

### run 25

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:23.546152+08:00 serve end job=daily pid=609 exit=0 seconds=24
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 59.80s
```

### run 26

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.206863+08:00 serve end job=daily pid=623 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.70s
```

### run 27

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:21.094234+08:00 serve end job=daily pid=634 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.30s
```

### run 28

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.005758+08:00 serve end job=daily pid=640 exit=0 seconds=20
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 57.21s
```

### run 29

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:22.594601+08:00 serve end job=daily pid=707 exit=0 seconds=23
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 58.91s
```

### run 30

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.842096+08:00 serve end job=daily pid=711 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.60s
```

### run 31

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:20.894062+08:00 serve end job=daily pid=725 exit=0 seconds=21
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.61s
```

### run 32

```
E       ValueError: not enough values to unpack (expected 2, got 1)
tests/test_worker_serve.py:982: ValueError
2026-10-16T23:00:19.313307+08:00 serve end job=daily pid=732 exit=0 seconds=19
=========================== short test summary info ============================
FAILED tests/test_worker_serve.py::test_what_the_2300_trigger_runs_after_the_2130_run[stuck]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 56.09s
```
