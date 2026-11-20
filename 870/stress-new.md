# 新寫法（必修 1 後，head 見 PR）加壓 32 次

條件：`docker run --cpus=2 --memory=6g`，容器內 8 支 `python -c "while 1: pass"` 燒 CPU，`xargs -P 4` 並行，只跑 `test_what_the_2300_trigger_runs_after_the_2130_run[stuck]`（[`loop.sh`](loop.sh) `32 8 4`）。

## 每次的結束碼

```
new run=1 exit=0 seconds=80 
new run=2 exit=0 seconds=80 
new run=3 exit=0 seconds=79 
new run=4 exit=0 seconds=80 
new run=5 exit=0 seconds=76 
new run=6 exit=0 seconds=75 
new run=7 exit=0 seconds=72 
new run=8 exit=0 seconds=74 
new run=9 exit=0 seconds=78 
new run=10 exit=0 seconds=74 
new run=11 exit=0 seconds=74 
new run=12 exit=0 seconds=74 
new run=13 exit=0 seconds=76 
new run=14 exit=0 seconds=72 
new run=15 exit=0 seconds=77 
new run=16 exit=0 seconds=74 
new run=17 exit=0 seconds=76 
new run=18 exit=0 seconds=73 
new run=19 exit=0 seconds=74 
new run=20 exit=0 seconds=73 
new run=21 exit=0 seconds=77 
new run=22 exit=0 seconds=74 
new run=23 exit=0 seconds=75 
new run=24 exit=0 seconds=72 
new run=25 exit=0 seconds=76 
new run=26 exit=0 seconds=74 
new run=27 exit=0 seconds=75 
new run=28 exit=0 seconds=72 
new run=29 exit=0 seconds=74 
new run=30 exit=0 seconds=73 
new run=31 exit=0 seconds=75 
new run=32 exit=0 seconds=72 
```

## 每次輸出：錯誤行（若有）與最後 5 行

### run 1

```
.                                                                        [100%]
1 passed in 71.11s (0:01:11)
```

### run 2

```
.                                                                        [100%]
1 passed in 70.51s (0:01:10)
```

### run 3

```
.                                                                        [100%]
1 passed in 70.00s (0:01:09)
```

### run 4

```
.                                                                        [100%]
1 passed in 70.50s (0:01:10)
```

### run 5

```
.                                                                        [100%]
1 passed in 67.00s (0:01:07)
```

### run 6

```
.                                                                        [100%]
1 passed in 66.21s (0:01:06)
```

### run 7

```
.                                                                        [100%]
1 passed in 64.00s (0:01:03)
```

### run 8

```
.                                                                        [100%]
1 passed in 65.30s (0:01:05)
```

### run 9

```
.                                                                        [100%]
1 passed in 68.91s (0:01:08)
```

### run 10

```
.                                                                        [100%]
1 passed in 65.70s (0:01:05)
```

### run 11

```
.                                                                        [100%]
1 passed in 66.09s (0:01:06)
```

### run 12

```
.                                                                        [100%]
1 passed in 65.51s (0:01:05)
```

### run 13

```
.                                                                        [100%]
1 passed in 67.49s (0:01:07)
```

### run 14

```
.                                                                        [100%]
1 passed in 63.69s (0:01:03)
```

### run 15

```
.                                                                        [100%]
1 passed in 68.79s (0:01:08)
```

### run 16

```
.                                                                        [100%]
1 passed in 66.89s (0:01:06)
```

### run 17

```
.                                                                        [100%]
1 passed in 67.69s (0:01:07)
```

### run 18

```
.                                                                        [100%]
1 passed in 64.60s (0:01:04)
```

### run 19

```
.                                                                        [100%]
1 passed in 65.50s (0:01:05)
```

### run 20

```
.                                                                        [100%]
1 passed in 64.11s (0:01:04)
```

### run 21

```
.                                                                        [100%]
1 passed in 68.69s (0:01:08)
```

### run 22

```
.                                                                        [100%]
1 passed in 66.40s (0:01:06)
```

### run 23

```
.                                                                        [100%]
1 passed in 67.30s (0:01:07)
```

### run 24

```
.                                                                        [100%]
1 passed in 64.19s (0:01:04)
```

### run 25

```
.                                                                        [100%]
1 passed in 67.90s (0:01:07)
```

### run 26

```
.                                                                        [100%]
1 passed in 65.30s (0:01:05)
```

### run 27

```
.                                                                        [100%]
1 passed in 67.49s (0:01:07)
```

### run 28

```
.                                                                        [100%]
1 passed in 63.70s (0:01:03)
```

### run 29

```
.                                                                        [100%]
1 passed in 65.51s (0:01:05)
```

### run 30

```
.                                                                        [100%]
1 passed in 65.51s (0:01:05)
```

### run 31

```
.                                                                        [100%]
1 passed in 68.30s (0:01:08)
```

### run 32

```
.                                                                        [100%]
1 passed in 63.91s (0:01:03)
```
