import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


QUICK = Path(__file__).resolve().parents[1] / "quick.sh"


@unittest.skipUnless(shutil.which("script"), "PTY test utility is unavailable")
class QuickEntryTests(unittest.TestCase):
    def test_provider_selection_preserves_tencent_and_direct_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "bin"
            binary.mkdir()
            arguments = root / "arguments"
            mocks = {
                "id": '#!/bin/sh\nprintf "0\\n"\n',
                "curl": '''#!/bin/sh
case "$*" in
  *169.254.0.23*) [ "$MODE" = tencent ] && { printf '198.51.100.254\n'; exit 0; }; exit 22 ;;
  *169.254.169.254*) [ "$MODE" = oracle ] && { printf '[]\n'; exit 0; }; exit 22 ;;
  *api.ipify.org*) printf '198.51.100.54\n'; exit 0 ;;
esac
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; : > "$1"; fi
  shift
done
''',
                "sha256sum": '#!/bin/sh\ncat >/dev/null\nexit 0\n',
                "tar": '#!/bin/sh\nexit 0\n',
                "python3": '#!/bin/sh\nprintf "%s\\n" "$@" > "$QUICK_ARGS_FILE"\n',
            }
            for name, body in mocks.items():
                path = binary / name
                path.write_text(body)
                path.chmod(0o755)
            for mode, expected in (("direct", None),
                                   ("tencent", "--tencent-nat-public-ip"),
                                   ("oracle", "--oracle-nat-public-ip")):
                with self.subTest(mode=mode):
                    env = os.environ.copy()
                    env.update(PATH=str(binary) + ":" + env["PATH"], MODE=mode,
                               QUICK_ARGS_FILE=str(arguments))
                    run = subprocess.run(["script", "-q", "-e", "-c",
                                          f"bash {QUICK}", "/dev/null"],
                                         env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    args = arguments.read_text().splitlines()
                    self.assertIn("--execute", args)
                    for flag in ("--tencent-nat-public-ip", "--oracle-nat-public-ip"):
                        self.assertEqual(flag in args, flag == expected)
                    arguments.unlink()

    def test_password_argument_and_env_enable_unattended_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "bin"
            binary.mkdir()
            arguments = root / "arguments"
            mocks = {
                "id": '#!/bin/sh\nprintf "0\\n"\n',
                "curl": '''#!/bin/sh
case "$*" in
  *169.254.0.23*|*169.254.169.254*) exit 22 ;;
esac
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; : > "$1"; fi
  shift
done
''',
                "sha256sum": '#!/bin/sh\ncat >/dev/null\nexit 0\n',
                "tar": '#!/bin/sh\nexit 0\n',
                "python3": '#!/bin/sh\nprintf "%s\\n" "$@" > "$QUICK_ARGS_FILE"\n',
            }
            for name, body in mocks.items():
                path = binary / name
                path.write_text(body)
                path.chmod(0o755)
            script_text = QUICK.read_text()
            for cmd_args, extra_env in (
                (["bash", "-s", "--", "Secret@123"], {}),
                (["bash", "-s", "--", "--password", "Secret@123"], {}),
                (["bash", "-s"], {"IKUAI_PASSWORD": "Secret@123"}),
            ):
                with self.subTest(cmd_args=cmd_args, extra_env=extra_env):
                    env = os.environ.copy()
                    env.update(PATH=str(binary) + ":" + env["PATH"], QUICK_ARGS_FILE=str(arguments), **extra_env)
                    run = subprocess.run(cmd_args, input=script_text, env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    args = arguments.read_text().splitlines()
                    self.assertIn("--password", args)
                    self.assertEqual(args[args.index("--password") + 1], "Secret@123")
                    self.assertIn("--yes", args)
                    self.assertIn("--execute", args)
                    arguments.unlink()


if __name__ == "__main__":
    unittest.main()
