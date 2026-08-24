import asyncio
import enum
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import minizinc
from discord import (
    Client,
    CustomActivity,
    Intents,
    Interaction,
    Message,
    SelectOption,
    app_commands,
    ui,
)


def get_time_str(statistics: dict[str, Any]) -> str:
    if not "time" in statistics:
        return "No Time"
    time = statistics["time"]
    if isinstance(time, timedelta):
        return f"{time.total_seconds()}s"
    elif isinstance(time, int):
        return f"{timedelta(milliseconds=time).total_seconds()}s"
    elif isinstance(time, float):
        return f"{time}s"
    else:
        return f"{time}"


# Initialise MiniZinc
mzn_version = minizinc.default_driver.parsed_version
no_solver = minizinc.Solver(
    "the MiniZinc standard library",
    f"{mzn_version[0]}.{mzn_version[1]}.{mzn_version[2]}",
    "com.discord.no_solver",
    "false",
)
# The first line is e.g. "MiniZinc to FlatZinc converter, version 2.10.1, build 32437703659"
mzn_build = minizinc.default_driver.minizinc_version.splitlines()[0].split(", ", 1)[-1]
STDLIB = "stdlib"

# Solvers offered in the options menu. The GUI and tool "solvers" are of no use
# here, and an unknown version means MiniZinc could not load the solver library.
SOLVERS = sorted(
    {
        s.id: s
        for solvers in minizinc.default_driver.available_solvers().values()
        for s in solvers
        if not s.isGUIApplication
        and "tool" not in s.tags
        and s.id != "org.minizinc.findmus"
        and s.version != "<unknown version>"
    }.values(),
    key=lambda s: s.name,
)


# Language tags that signal a code block contains data instead of a model
DATA_TAGS = {"dzn", "json"}
# File types that can be part of a MiniZinc instance
SUFFIXES = {".mzn"} | {f".{tag}" for tag in DATA_TAGS}
# Limit on the size of the attachments, to avoid compiling something absurd
MAX_ATTACHED = 1024 * 1024


# Common functions
def extract_code(content: str, fenced_only: bool = False) -> list[tuple[str, str]]:
    r"""Extract the code blocks of a Discord message and the files they belong in

    The language tag of a block signals whether it contains data, everything
    else is considered part of the model. A message without any code fence is
    taken to be code in full, unless ``fenced_only`` is set.

    >>> extract_code("```mzn\nvar 1..3: x;\n```")
    [('.mzn', 'var 1..3: x;\n')]
    >>> extract_code("model\n```\nint: n;\n```\nand data\n```dzn\nn = 4;\n```")
    [('.mzn', 'int: n;\n'), ('.dzn', 'n = 4;\n')]
    >>> extract_code("`var 1..3: x;`")
    [('.mzn', 'var 1..3: x;')]
    >>> extract_code("can someone solve the attached?", fenced_only=True)
    []
    """
    blocks = re.findall(r"```[ \t]*(?:([\w+#-]*)[ \t]*\n)?(.*?)```", content, re.DOTALL)
    if len(blocks) == 0 and not fenced_only:
        blocks = [("", content.strip("` \t"))]
    return [
        (f".{tag}" if tag in DATA_TAGS else ".mzn", code)
        for tag, code in blocks
        if code.strip() != ""
    ]


@asynccontextmanager
async def instance_files(message: Message) -> AsyncIterator[list[Path]]:
    """Collect the MiniZinc files of a message in a temporary directory

    Both the attachments and the code blocks of the message are used. Files
    keep their name, so they can `include` each other. Included files are left
    out of the instance itself, since including them again would be an error.
    """
    with TemporaryDirectory() as directory:
        files = []
        budget = MAX_ATTACHED
        for attachment in message.attachments:
            name = Path(attachment.filename).name
            if Path(name).suffix not in SUFFIXES or attachment.size > budget:
                continue
            budget -= attachment.size
            path = Path(directory) / name
            path.write_bytes(await attachment.read())
            files.append(path)
        blocks = extract_code(message.content, fenced_only=len(files) > 0)
        for i, (suffix, code) in enumerate(blocks):
            path = Path(directory) / f"message{i}{suffix}"
            path.write_text(code)
            files.append(path)
        included = {
            name
            for file in files
            if file.suffix == ".mzn"
            for name in re.findall(r'include\s*"([^"]+)"', file.read_text())
        }
        yield [file for file in files if file.name not in included]


def check_model(files: list[Path]) -> str | None:
    """Return the problem with the instance, if MiniZinc finds one"""
    if len(files) == 0:
        return "This message does not contain any MiniZinc code."
    try:
        instance = minizinc.Instance(no_solver)
        for file in files:
            instance.add_file(file)
        # Runs `minizinc --model-interface-only`, which parses and type checks
        instance.analyse()
    except minizinc.MiniZincError as err:
        return str(err)
    return None


async def solve(
    interaction: Interaction,
    files: list[Path],
    solver: minizinc.Solver,
    time_limit: int,
):
    await interaction.response.defer(thinking=True)

    time_limit = timedelta(seconds=time_limit)

    try:
        instance = minizinc.Instance(solver)
        for file in files:
            instance.add_file(file)
        result = await instance.solve_async(timeout=time_limit)
        sol = str(result.solution) if result.solution is not None else "No Solution"
        if len(sol) > 1800:
            sol = sol[:1800]
            sol += "\n% ...TRUNCATED..."
        await interaction.followup.send(
            f"{solver.name}, version {solver.version}, reported `{result.status}` in {get_time_str(result.statistics)}:```{sol}```",
        )
    except minizinc.MiniZincError as err:
        await interaction.followup.send(f"```{err!s}```")


async def flatten(
    interaction: Interaction,
    files: list[Path],
    solver: minizinc.Solver,
    time_limit: int,
):
    await interaction.response.defer(thinking=True)

    time_limit = timedelta(seconds=time_limit)

    try:
        instance = minizinc.Instance(solver)
        for file in files:
            instance.add_file(file)
        with instance.flat(timeout=time_limit) as (fzn, _ozn, _statistics):
            flatzinc = Path(fzn.name).read_text()
            if len(flatzinc) > 1800:
                flatzinc = flatzinc[:1800]
                flatzinc += "\n% ...TRUNCATED..."
            await interaction.followup.send(
                f"Using the definitions of {solver.name}, version {solver.version}, this resulted in the following FlatZinc:```{flatzinc}```"
            )
            # FIXME: Full FlatZinc should be attached as a file when exceeding
    except minizinc.MiniZincError as err:
        await interaction.followup.send(f"```{err!s}```")


class MZNAction(enum.Enum):
    SOLVE = enum.auto()
    FLATTEN = enum.auto()


class OptionModal(ui.Modal):
    def __init__(
        self, message: Message, action: MZNAction, warning: str | None = None
    ) -> None:
        self.message = message
        self.action = action
        solving = action == MZNAction.SOLVE
        super().__init__(
            title="MiniZinc Solve Options" if solving else "MiniZinc Flatten Options"
        )

        if warning is not None:
            self.add_item(
                ui.TextDisplay(
                    f"⚠️ MiniZinc reports the following problem with this message. "
                    f"You can continue anyway.\n```{warning[:1000]}```"
                )
            )

        default = "org.gecode.gecode" if solving else STDLIB
        options = [
            SelectOption(
                label=f"{s.name} {s.version}", value=s.id, default=s.id == default
            )
            for s in SOLVERS
        ]
        if not solving:
            options.insert(
                0, SelectOption(label=no_solver.name, value=STDLIB, default=True)
            )
        # Discord shows at most 25 choices
        self.solver = ui.Select(options=options[:25])
        self.time_limit = ui.TextInput(default="15")
        self.add_item(ui.Label(text="Solver", component=self.solver))
        self.add_item(
            ui.Label(
                text="Time Limit",
                description="in seconds, at most 30",
                component=self.time_limit,
            )
        )

    @classmethod
    async def create(cls, message: Message, action: MZNAction) -> "OptionModal":
        """Create the modal, warning about any problem with the message"""
        try:
            async with instance_files(message) as files:
                warning = await asyncio.wait_for(
                    asyncio.to_thread(check_model, files), timeout=2
                )
        except asyncio.TimeoutError:
            warning = None  # Leave it to the time limit of the action itself
        return cls(message, action, warning)

    async def on_submit(self, interaction: Interaction):
        try:
            time_limit = int(self.time_limit.value)
        except ValueError:
            await interaction.response.send_message(
                f"expected integer time limit, received {self.time_limit.value}",
                ephemeral=True,
            )
            return
        if time_limit > 30:
            await interaction.response.send_message(
                "time limit cannot be set to more than 30 seconds", ephemeral=True
            )
            return

        choice = self.solver.values[0]
        solver = no_solver if choice == STDLIB else minizinc.Solver.lookup(choice)

        async with instance_files(self.message) as files:
            if self.action == MZNAction.SOLVE:
                await solve(interaction, files, solver, time_limit)
            else:
                await flatten(interaction, files, solver, time_limit)


@app_commands.context_menu(name="Solve MiniZinc")
async def solve_menu(interaction: Interaction, message: Message):
    await interaction.response.send_modal(
        await OptionModal.create(message, MZNAction.SOLVE)
    )


@app_commands.context_menu(name="Flatten MiniZinc")
async def flatten_menu(interaction: Interaction, message: Message):
    await interaction.response.send_modal(
        await OptionModal.create(message, MZNAction.FLATTEN)
    )


# A command group that combines the MiniZinc commands
class MZN(app_commands.Group):
    def __init__(self):
        super().__init__(name="mzn")

    @app_commands.command(description="Get the version of the MiniZinc compiler")
    @app_commands.describe(announce="Send version response to everyone in the channel")
    async def version(self, interaction: Interaction, announce: bool = False) -> None:
        response = minizinc.default_driver.minizinc_version
        await interaction.response.send_message(response, ephemeral=not announce)


class MZNClient(Client):
    def __init__(self):
        # Initialise super
        intents = Intents.default()
        intents.message_content = True
        super().__init__(
            intents=intents, activity=CustomActivity(name=f"MiniZinc {mzn_build}")
        )

        # Create tree object to add commands to
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.add_command(MZN())
        self.tree.add_command(solve_menu)
        self.tree.add_command(flatten_menu)
        await self.tree.sync()

    async def on_ready(self):
        print(
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} - {self.user} has connected to Discord!"
        )


if __name__ == "__main__":
    # Initialise Discord bot
    TOKEN = os.getenv("DISCORD_TOKEN")

    client = MZNClient()
    client.run(TOKEN)
