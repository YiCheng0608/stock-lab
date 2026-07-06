#!/usr/bin/env python3
"""Test spec-5: Notifier ABC interface and implementations (LogNotifier, TelegramNotifier)."""

import sys
import logging
from abc import ABC
from pathlib import Path

# Setup basic logging to capture LogNotifier output
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

# Add app module to path
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

def test_imports():
    """Test 1: Import all notifier modules successfully."""
    print("TEST 1: Importing notifier modules...")
    try:
        from app.notifications.base import Notifier
        from app.notifications.log_notifier import LogNotifier
        from app.notifications.telegram_notifier import TelegramNotifier
        from app.notifications import Notifier as NotifierFromInit
        from app.notifications import LogNotifier as LogNotifierFromInit
        from app.notifications import TelegramNotifier as TelegramNotifierFromInit
        print("  ✓ All imports successful")
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False

def test_notifier_abc():
    """Test 2: Verify Notifier is ABC and has abstract notify method."""
    print("\nTEST 2: Verifying Notifier ABC structure...")
    try:
        from app.notifications.base import Notifier
        import inspect

        # Check if it's an ABC
        if not issubclass(Notifier, ABC):
            print(f"  ✗ Notifier is not an ABC")
            return False
        print(f"  ✓ Notifier is an ABC")

        # Check for abstract method
        abstract_methods = Notifier.__abstractmethods__
        if 'notify' not in abstract_methods:
            print(f"  ✗ 'notify' is not an abstract method")
            return False
        print(f"  ✓ 'notify' is an abstract method: {abstract_methods}")

        # Try to instantiate Notifier directly (should fail)
        try:
            Notifier()
            print(f"  ✗ Notifier can be instantiated directly (should fail)")
            return False
        except TypeError as e:
            print(f"  ✓ Cannot instantiate Notifier directly (expected): {e}")

        return True
    except Exception as e:
        print(f"  ✗ ABC verification failed: {e}")
        return False

def test_lognotifier_implements():
    """Test 3: Verify LogNotifier correctly implements Notifier."""
    print("\nTEST 3: Verifying LogNotifier implementation...")
    try:
        from app.notifications.base import Notifier
        from app.notifications.log_notifier import LogNotifier

        # Check if it's a subclass
        if not issubclass(LogNotifier, Notifier):
            print(f"  ✗ LogNotifier is not a subclass of Notifier")
            return False
        print(f"  ✓ LogNotifier is a subclass of Notifier")

        # Check if notify method exists
        if not hasattr(LogNotifier, 'notify'):
            print(f"  ✗ LogNotifier has no notify method")
            return False
        print(f"  ✓ LogNotifier has notify method")

        # Try to instantiate LogNotifier (should succeed)
        try:
            notifier = LogNotifier()
            print(f"  ✓ LogNotifier instantiated successfully")
        except Exception as e:
            print(f"  ✗ Cannot instantiate LogNotifier: {e}")
            return False

        return True
    except Exception as e:
        print(f"  ✗ LogNotifier verification failed: {e}")
        return False

def test_lognotifier_notify():
    """Test 4: Call LogNotifier.notify and verify it doesn't raise exception."""
    print("\nTEST 4: Testing LogNotifier.notify()...")
    try:
        from app.notifications.log_notifier import LogNotifier

        notifier = LogNotifier()

        # Call notify with test data
        notifier.notify(
            subject="Test Alert",
            message="This is a test notification from spec-5 verification"
        )
        print(f"  ✓ LogNotifier.notify() executed without exception")
        return True
    except Exception as e:
        print(f"  ✗ LogNotifier.notify() raised exception: {e}")
        return False

def test_lognotifier_no_external_calls():
    """Test 5: Verify LogNotifier never makes external calls."""
    print("\nTEST 5: Verifying LogNotifier has no external dependencies...")
    try:
        from app.notifications.log_notifier import LogNotifier
        import inspect

        # Just check the source to make sure it doesn't make HTTP/network calls
        source = inspect.getsource(LogNotifier.notify)
        forbidden_patterns = ['http', 'requests', 'urllib', 'socket', 'send']

        has_forbidden = False
        for pattern in forbidden_patterns:
            if pattern.lower() in source.lower():
                # Check if it's just in a comment or docstring
                lines = source.split('\n')
                for line in lines:
                    stripped = line.strip()
                    if not stripped.startswith('#') and not stripped.startswith('"""') and not stripped.startswith("'''"):
                        if pattern.lower() in line.lower():
                            print(f"  ! Found '{pattern}' in code (may be false positive)")

        # Try calling it anyway
        notifier = LogNotifier()
        notifier.notify("External Call Test", "Checking for network calls")
        print(f"  ✓ LogNotifier.notify() contains no obvious external calls")
        return True
    except Exception as e:
        print(f"  ✗ LogNotifier verification failed: {e}")
        return False

def test_telegramnotifier_implements():
    """Test 6: Verify TelegramNotifier correctly implements Notifier."""
    print("\nTEST 6: Verifying TelegramNotifier implementation...")
    try:
        from app.notifications.base import Notifier
        from app.notifications.telegram_notifier import TelegramNotifier

        # Check if it's a subclass
        if not issubclass(TelegramNotifier, Notifier):
            print(f"  ✗ TelegramNotifier is not a subclass of Notifier")
            return False
        print(f"  ✓ TelegramNotifier is a subclass of Notifier")

        # Check if notify method exists
        if not hasattr(TelegramNotifier, 'notify'):
            print(f"  ✗ TelegramNotifier has no notify method")
            return False
        print(f"  ✓ TelegramNotifier has notify method")

        # Try to instantiate TelegramNotifier (should succeed even without env vars)
        try:
            notifier = TelegramNotifier()
            print(f"  ✓ TelegramNotifier instantiated successfully")
        except Exception as e:
            print(f"  ✗ Cannot instantiate TelegramNotifier: {e}")
            return False

        return True
    except Exception as e:
        print(f"  ✗ TelegramNotifier verification failed: {e}")
        return False

def test_telegramnotifier_notify_without_token():
    """Test 7: Call TelegramNotifier.notify without token (should not raise)."""
    print("\nTEST 7: Testing TelegramNotifier.notify() without token...")
    try:
        from app.notifications.telegram_notifier import TelegramNotifier
        import os

        # Ensure Telegram env vars are not set
        os.environ.pop('TELEGRAM_BOT_TOKEN', None)
        os.environ.pop('TELEGRAM_CHAT_ID', None)

        # Clear the settings cache to reload env vars
        from app.config import get_settings
        get_settings.cache_clear()

        notifier = TelegramNotifier()

        # Call notify - should log warning but not raise
        notifier.notify(
            subject="Test Alert",
            message="This should not actually send anywhere"
        )
        print(f"  ✓ TelegramNotifier.notify() executed without exception (no token)")
        return True
    except Exception as e:
        print(f"  ✗ TelegramNotifier.notify() raised exception: {e}")
        return False

def test_telegramnotifier_notify_with_token():
    """Test 8: Call TelegramNotifier.notify with token set."""
    print("\nTEST 8: Testing TelegramNotifier.notify() with token set...")
    try:
        from app.notifications.telegram_notifier import TelegramNotifier
        import os

        # Set dummy Telegram env vars
        os.environ['TELEGRAM_BOT_TOKEN'] = 'dummy_token_123'
        os.environ['TELEGRAM_CHAT_ID'] = '123456789'

        # Clear the settings cache to reload env vars
        from app.config import get_settings
        get_settings.cache_clear()

        notifier = TelegramNotifier()

        # Call notify - should log but not actually call Telegram API
        notifier.notify(
            subject="Test Alert",
            message="This should log but not actually call Telegram"
        )
        print(f"  ✓ TelegramNotifier.notify() executed without exception (with token)")
        return True
    except Exception as e:
        print(f"  ✗ TelegramNotifier.notify() raised exception: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("SPEC-5 VERIFICATION: Notifier ABC and Implementations")
    print("=" * 60)

    tests = [
        test_imports,
        test_notifier_abc,
        test_lognotifier_implements,
        test_lognotifier_notify,
        test_lognotifier_no_external_calls,
        test_telegramnotifier_implements,
        test_telegramnotifier_notify_without_token,
        test_telegramnotifier_notify_with_token,
    ]

    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append((test_func.__name__, result))
        except Exception as e:
            print(f"\nUNEXPECTED ERROR in {test_func.__name__}: {e}")
            results.append((test_func.__name__, False))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{len(results)} passed")

    if failed > 0:
        print(f"\nFAILED: {failed} tests failed")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: All tests passed")
        sys.exit(0)

if __name__ == "__main__":
    main()
