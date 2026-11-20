# nohold：暫時不建 holding 檔的 child（副本掛進容器，不 commit）

```
E       AssertionError: assert False == ('stuck' == 'stuck'
E        +  where False = exists()
E        +    where exists = PosixPath('/tmp/pytest-of-app/pytest-0/test_what_the_2300_trigger_run0/holding').exists
E         
E           stuck)
tests/test_worker_serve.py:998: AssertionError
2026-10-16T21:30:00.005878+08:00 serve start job=daily pid=16
2026-10-16T21:31:00.203062+08:00 serve end job=daily pid=16 exit=1 seconds=60
1 failed in 65.11s (0:01:05)
wall=66s
```
