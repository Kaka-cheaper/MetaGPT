import asyncio
import os
import re
import platform
import subprocess
from asyncio import Queue
from asyncio.subprocess import PIPE, STDOUT
from pathlib import Path
from typing import Optional

from metagpt.config2 import Config
from metagpt.const import DEFAULT_WORKSPACE_ROOT, SWE_SETUP_PATH
from metagpt.logs import logger
from metagpt.tools.tool_registry import register_tool
from metagpt.utils.report import END_MARKER_VALUE, TerminalReporter


@register_tool()
class Terminal:
    """
    A tool for running terminal commands.
    Don't initialize a new instance of this class if one already exists.
    For commands that need to be executed within a Conda environment, it is recommended
    to use the `execute_in_conda_env` method.
    """

    # def __init__(self):
    #     # self.shell_command = ["bash"]  # FIXME: should consider windows support later
    #     # self.command_terminator = "\n"
    #     # 根据操作系统选择shell
    #     self.shell_command = ["cmd.exe"] if os.name == 'nt' else ["bash"]
    #     # 调整命令终止符
    #     self.command_terminator = "\r\n" if os.name == 'nt' else "\n"
    #     self.stdout_queue = Queue(maxsize=1000)
    #     self.observer = TerminalReporter()
    #     self.process: Optional[asyncio.subprocess.Process] = None
    #     #  The cmd in forbidden_terminal_commands will be replace by pass ana return the advise. example:{"cmd":"forbidden_reason/advice"}
    #     self.forbidden_commands = {
    #         "run dev": "Use Deployer.deploy_to_public instead.",
    #         # serve cmd have a space behind it,
    #         "serve ": "Use Deployer.deploy_to_public instead.",
    #     }
    def __init__(self):
        self.is_windows = platform.system() == 'Windows'
        self.shell_command = ["cmd.exe", "/K"] if self.is_windows else ["bash"]
        self.command_terminator = "\r\n" if self.is_windows else "\n"
        self.win_cmd_map = {
            "pwd": "echo %cd%",
            "ls": "dir /b",
            "mkdir -p": "mkdir",
            "/": "\\",
            "source": "call"
        }
        self.stdout_queue = Queue(maxsize=1000)
        self.observer = TerminalReporter()
        self.process: Optional[asyncio.subprocess.Process] = None
        self.forbidden_commands = {
            "run dev": "Use Deployer.deploy_to_public instead.",
            "serve ": "Use Deployer.deploy_to_public instead.",
        }
        self.encoding = 'gbk' if platform.system() == 'Windows' else 'utf-8'

    # async def _start_process(self):
    #     # Start a persistent shell process
    #     self.process = await asyncio.create_subprocess_exec(
    #         *self.shell_command,
    #         stdin=PIPE,
    #         stdout=PIPE,
    #         stderr=STDOUT,
    #         executable="bash",
    #         env=os.environ.copy(),
    #         cwd=DEFAULT_WORKSPACE_ROOT.absolute(),
    #     )
    #     await self._check_state()
    async def _start_process(self):
        """Start a persistent shell process with platform-specific settings"""
        env = os.environ.copy()
        startupinfo = None
        if self.is_windows:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            env['PYTHONIOENCODING'] = 'utf-8'  # 强制Python使用UTF-8编码
            env['CHCP'] = '65001'  # 设置控制台代码页为UTF-8

        self.process = await asyncio.create_subprocess_exec(
            *self.shell_command,
            stdin=PIPE,
            stdout=PIPE,
            stderr=STDOUT,
            executable=None if self.is_windows else "bash",
            startupinfo=startupinfo,
            env=env,
            cwd=str(DEFAULT_WORKSPACE_ROOT.absolute()),
        )
        await self._check_state()

    # async def _check_state(self):
    #     """
    #     Check the state of the terminal, e.g. the current directory of the terminal process. Useful for agent to understand.
    #     """
    #     output = await self.run_command("pwd")
    #     logger.info("The terminal is at:", output)
    async def _check_state(self):
        """Check and log current directory"""
        cmd = "echo %cd%" if self.is_windows else "pwd"
        output = (await self.run_command(cmd)).strip()
        logger.info(f"Terminal current directory: {output}")

    def _convert_command(self, cmd: str) -> str:
        """Convert Unix commands to Windows equivalents with safe regex handling"""
        cmd = cmd.replace('\xa0', ' ')  # 替换不间断空格
        cmd = cmd.encode(self.encoding, errors='replace').decode(self.encoding)
        if not self.is_windows:
            return cmd

        try:
            # 使用pathlib进行路径标准化
            from pathlib import Path
            cmd = str(Path(cmd).as_posix()).replace('/', '\\')

            # 安全替换命令
            for unix_cmd, win_cmd in self.win_cmd_map.items():
                # 构建精确匹配模式
                pattern = r'(?<!\\)\b' + re.escape(unix_cmd) + r'\b'
                cmd = re.sub(pattern, lambda m: win_cmd, cmd, flags=re.IGNORECASE)

            # 处理特殊命令参数
            cmd = re.sub(r'\bmkdir -p\b', 'mkdir', cmd, flags=re.IGNORECASE)

            logger.debug(f"Converted command: {cmd}")  # 添加调试日志
            return cmd
        except Exception as e:
            logger.error(f"Command conversion error: {str(e)}")
            return cmd

    # async def run_command(self, cmd: str, daemon=False) -> str:
    #     """
    #     Executes a specified command in the terminal and streams the output back in real time.
    #     This command maintains state across executions, such as the current directory,
    #     allowing for sequential commands to be contextually aware.
    #
    #     Args:
    #         cmd (str): The command to execute in the terminal.
    #         daemon (bool): If True, executes the command in an asynchronous task, allowing
    #                        the main program to continue execution.
    #     Returns:
    #         str: The command's output or an empty string if `daemon` is True. Remember that
    #              when `daemon` is True, use the `get_stdout_output` method to get the output.
    #     """
    #
    #     # 转换Unix风格路径到Windows格式
    #     if os.name == 'nt':
    #         cmd = cmd.replace('/', '\\')
    #         cmd = re.sub(r'mkdir -p', 'mkdir', cmd)  # Windows不需要-p参数
    #
    #     if self.process is None:
    #         await self._start_process()
    #
    #     output = ""
    #     # Remove forbidden commands
    #     commands = re.split(r"\s*&&\s*", cmd)
    #     for cmd_name, reason in self.forbidden_commands.items():
    #         # "true" is a pass command in linux terminal.
    #         for index, command in enumerate(commands):
    #             if cmd_name in command:
    #                 output += f"Failed to execut {command}. {reason}\n"
    #                 commands[index] = "true"
    #     cmd = " && ".join(commands)
    #
    #     # Send the command
    #     self.process.stdin.write((cmd + self.command_terminator).encode())
    #     self.process.stdin.write(
    #         f'echo "{END_MARKER_VALUE}"{self.command_terminator}'.encode()  # write EOF
    #     )  # Unique marker to signal command end
    #     await self.process.stdin.drain()
    #     if daemon:
    #         asyncio.create_task(self._read_and_process_output(cmd))
    #     else:
    #         output += await self._read_and_process_output(cmd)
    #
    #     return output
    async def run_command(self, cmd: str, daemon=False) -> str:
        """Execute command with platform-specific adaptations"""
        cmd = self._convert_command(cmd)

        if self.process is None:
            await self._start_process()

        # Command filtering logic
        output = ""
        commands = re.split(r"\s*&&\s*", cmd)
        for cmd_name, reason in self.forbidden_commands.items():
            for index, command in enumerate(commands):
                if cmd_name in command:
                    output += f"Blocked command: {command}. {reason}\n"
                    commands[index] = "echo"  # Windows compatible no-op

        cmd = " && ".join(commands)

        # Send command with platform-specific termination
        full_cmd = f"{cmd}{self.command_terminator}echo {END_MARKER_VALUE}{self.command_terminator}"
        self.process.stdin.write(full_cmd.encode())
        await self.process.stdin.drain()

        return await self._read_and_process_output(cmd) if not daemon else ""

    async def execute_in_conda_env(self, cmd: str, env, daemon=False) -> str:
        """
        Executes a given command within a specified Conda environment automatically without
        the need for manual activation. Users just need to provide the name of the Conda
        environment and the command to execute.

        Args:
            cmd (str): The command to execute within the Conda environment.
            env (str, optional): The name of the Conda environment to activate before executing the command.
                                 If not specified, the command will run in the current active environment.
            daemon (bool): If True, the command is run in an asynchronous task, similar to `run_command`,
                           affecting error logging and handling in the same manner.

        Returns:
            str: The command's output, or an empty string if `daemon` is True, with output processed
                 asynchronously in that case.

        Note:
            This function wraps `run_command`, prepending the necessary Conda activation commands
            to ensure the specified environment is active for the command's execution.
        """
        cmd = f"conda run -n {env} {cmd}"
        return await self.run_command(cmd, daemon=daemon)

    async def get_stdout_output(self) -> str:
        """
        Retrieves all collected output from background running commands and returns it as a string.

        Returns:
            str: The collected output from background running commands, returned as a string.
        """
        output_lines = []
        while not self.stdout_queue.empty():
            line = await self.stdout_queue.get()
            output_lines.append(line)
        return "\n".join(output_lines)

    # async def _read_and_process_output(self, cmd, daemon=False) -> str:
    #     async with self.observer as observer:
    #         cmd_output = []
    #         await observer.async_report(cmd + self.command_terminator, "cmd")
    #         # report the command
    #         # Read the output until the unique marker is found.
    #         # We read bytes directly from stdout instead of text because when reading text,
    #         # '\r' is changed to '\n', resulting in excessive output.
    #         tmp = b""
    #         while True:
    #             output = tmp + await self.process.stdout.read(1)
    #             if not output:
    #                 continue
    #             *lines, tmp = output.splitlines(True)
    #             for line in lines:
    #                 line = line.decode()
    #                 ix = line.rfind(END_MARKER_VALUE)
    #                 if ix >= 0:
    #                     line = line[0:ix]
    #                     if line:
    #                         await observer.async_report(line, "output")
    #                         # report stdout in real-time
    #                         cmd_output.append(line)
    #                     return "".join(cmd_output)
    #                 # log stdout in real-time
    #                 await observer.async_report(line, "output")
    #                 cmd_output.append(line)
    #                 if daemon:
    #                     await self.stdout_queue.put(line)
    async def _read_and_process_output(self, cmd, daemon=False) -> str:
        async with self.observer as observer:
            cmd_output = []
            await observer.async_report(cmd + self.command_terminator, "cmd")

            tmp = b""
            while True:
                output = tmp + await self.process.stdout.read(1024)  # 增加读取缓冲区
                if not output:
                    continue
                *lines, tmp = output.splitlines(True)

                for line in lines:
                    try:
                        # 使用动态检测的编码解码
                        decoded_line = line.decode(self.encoding, errors='replace')
                        # 清理Windows特有的控制台字符
                        clean_line = re.sub(r'\x1b\[\d+?m', '', decoded_line)  # 移除ANSI颜色代码
                    except UnicodeDecodeError:
                        # 备选解码方案
                        decoded_line = line.decode('utf-8', errors='replace')

                    ix = decoded_line.rfind(END_MARKER_VALUE)
                    if ix >= 0:
                        clean_line = decoded_line[0:ix].replace('\x00', '')
                        if clean_line:
                            await observer.async_report(clean_line, "output")
                            cmd_output.append(clean_line)
                        return "".join(cmd_output)

                    # 过滤无效字符
                    clean_line = decoded_line.replace('\x00', '').replace('\r\r\n', '\n')
                    await observer.async_report(clean_line, "output")
                    cmd_output.append(clean_line)
                    if daemon:
                        await self.stdout_queue.put(clean_line)

    async def close(self):
        """Close the persistent shell process."""
        self.process.stdin.close()
        await self.process.wait()


@register_tool(include_functions=["run"])
class Bash(Terminal):
    """
    A class to run bash commands directly and provides custom shell functions.
    All custom functions in this class can ONLY be called via the `Bash.run` method.
    """

    def __init__(self):
        """init"""
        os.environ["SWE_CMD_WORK_DIR"] = str(Config.default().workspace.path)
        super().__init__()
        self.start_flag = False

    # async def start(self):
    #     await self.run_command(f"cd {Config.default().workspace.path}")
    #     await self.run_command(f"source {SWE_SETUP_PATH}")
    async def start(self):
        """Windows compatible initialization"""
        if self.is_windows:
            await self.run_command(f"cd /D {Config.default().workspace.path}")
            setup_path = Path(SWE_SETUP_PATH).as_posix().replace('/', '\\')
            await self.run_command(f"call {setup_path}")
        else:
            await self.run_command(f"cd {Config.default().workspace.path}")
            await self.run_command(f"source {SWE_SETUP_PATH}")
        self.start_flag = True

    async def run(self, cmd) -> str:
        """
        Executes a bash command.

        Args:
            cmd (str): The bash command to execute.

        Returns:
            str: The output of the command.

        This method allows for executing standard bash commands as well as
        utilizing several custom shell functions defined in the environment.

        Custom Shell Functions:

        - open <path> [<line_number>]
          Opens the file at the given path in the editor. If line_number is provided,
          the window will move to include that line.
          Arguments:
              path (str): The path to the file to open.
              line_number (int, optional): The line number to move the window to.
              If not provided, the window will start at the top of the file.

        - goto <line_number>
          Moves the window to show <line_number>.
          Arguments:
              line_number (int): The line number to move the window to.

        - scroll_down
          Moves the window down {WINDOW} lines.

        - scroll_up
          Moves the window up {WINDOW} lines.

        - create <filename>
          Creates and opens a new file with the given name.
          Arguments:
              filename (str): The name of the file to create.

        - search_dir_and_preview <search_term> [<dir>]
          Searches for search_term in all files in dir and gives their code preview
          with line numbers. If dir is not provided, searches in the current directory.
          Arguments:
              search_term (str): The term to search for.
              dir (str, optional): The directory to search in. Defaults to the current directory.

        - search_file <search_term> [<file>]
          Searches for search_term in file. If file is not provided, searches in the current open file.
          Arguments:
              search_term (str): The term to search for.
              file (str, optional): The file to search in. Defaults to the current open file.

        - find_file <file_name> [<dir>]
          Finds all files with the given name in dir. If dir is not provided, searches in the current directory.
          Arguments:
              file_name (str): The name of the file to search for.
              dir (str, optional): The directory to search in. Defaults to the current directory.

        - edit <start_line>:<end_line> <<EOF
          <replacement_text>
          EOF
          Line numbers start from 1. Replaces lines <start_line> through <end_line> (inclusive) with the given text in the open file.
          The replacement text is terminated by a line with only EOF on it. All of the <replacement text> will be entered, so make
          sure your indentation is formatted properly. Python files will be checked for syntax errors after the edit. If the system
          detects a syntax error, the edit will not be executed. Simply try to edit the file again, but make sure to read the error
          message and modify the edit command you issue accordingly. Issuing the same command a second time will just lead to the same
          error message again. All code modifications made via the 'edit' command must strictly follow the PEP8 standard.
          Arguments:
              start_line (int): The line number to start the edit at, starting from 1.
              end_line (int): The line number to end the edit at (inclusive), starting from 1.
              replacement_text (str): The text to replace the current selection with, must conform to PEP8 standards.

        - submit
          Submits your current code locally. it can only be executed once, the last action before the `end`.

        Note: Make sure to use these functions as per their defined arguments and behaviors.
        """
        # if not self.start_flag:
        #     await self.start()
        #     self.start_flag = True
        #
        # return await self.run_command(cmd)
        if not self.start_flag:
            await self.start()

            # Convert Unix-style paths for Windows
        if self.is_windows:
            cmd = str(Path(cmd).as_posix()).replace('/', '\\')

        return await super().run_command(cmd)
