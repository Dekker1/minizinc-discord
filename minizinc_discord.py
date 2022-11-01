import enum
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import minizinc
from discord import Intents, Interaction, Message, app_commands, Client, ui


def get_time_str(statistics: Dict[str, Any]) -> str:
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

# Common functions
async def solve(
    interaction: Interaction,
    code: str,
    solver: minizinc.Solver,
    time_limit: int,
):
    await interaction.response.defer(thinking=True)

    code = code.strip("` \t")
    time_limit = timedelta(seconds=time_limit)

    try:
        instance = minizinc.Instance(solver)
        instance.add_string(code)
        result = await instance.solve_async(timeout=time_limit)
        sol = str(result.solution) if result.solution is not None else "No Solution"
        if len(sol) > 1800:
            sol = sol[:1800]
            sol += "\n% ...TRUNCATED..."
        await interaction.followup.send(
            f"{solver.name}, version {solver.version}, reported `{result.status}` in {get_time_str(result.statistics)}:```{sol}```",
        )
    except minizinc.MiniZincError as err:
        await interaction.followup.send(f"```{str(err)}```")


async def flatten(
    interaction: Interaction, code: str, solver: minizinc.Solver, time_limit: int
):
    await interaction.response.defer(thinking=True)

    code = code.strip("` \t")
    time_limit = timedelta(seconds=time_limit)

    try:
        instance = minizinc.Instance(solver)
        instance.add_string(code)
        with instance.flat(timeout=time_limit) as (fzn, ozn, statistics):
            flatzinc = Path(fzn.name).read_text()
            if len(flatzinc) > 1800:
                flatzinc = flatzinc[:1800]
                flatzinc += "\n% ...TRUNCATED..."
            await interaction.followup.send(
                f"Using the definitions of {solver.name}, version {solver.version}, this resulted in the following FlatZinc:```{flatzinc}```"
            )
            # FIXME: Full FlatZinc should be attached as a file when exceeding
    except minizinc.MiniZincError as err:
        await interaction.followup.send(f"```{str(err)}```")


class MZNAction(enum.Enum):
    SOLVE = enum.auto()
    FLATTEN = enum.auto()


class OptionModal(ui.Modal):
    solver = ui.TextInput(label="Solver")
    # solver = ui.Select(options=["cbc", "chuffed", "gecode"], placeholder="chuffed")
    time_limit = ui.TextInput(label="Time Limit", default="15")

    def __init__(self, message: Message, action: MZNAction) -> None:
        self.message = message
        self.action = action
        if action == MZNAction.SOLVE:
            title = "MiniZinc Solve Options"
            self.solver.default = "gecode"
        else:
            title = "MiniZinc Flatten Options"
            self.solver.default = "stdlib"
        super().__init__(title=title)

    async def on_submit(self, interaction: Interaction):
        time_limit = 15
        try:
            time_limit = int(self.time_limit.value)
            if time_limit > 30:
                await interaction.response.send_message(
                    f"time limit cannot be set to more than 30 seconds", ephemeral=True
                )
        except ValueError:
            await interaction.response.send_message(
                f"expected integer time limit, received {self.time_limit.value}",
                ephemeral=True,
            )

        try:
            if self.action == MZNAction.FLATTEN and self.solver.value == "stdlib":
                solver = no_solver
            else:
                solver = minizinc.Solver.lookup(self.solver.value)
        except LookupError:
            await interaction.response.send_message(
                f"solver {self.time_limit.value} could not be found", ephemeral=True
            )

        if self.action == MZNAction.SOLVE:
            await solve(interaction, self.message.content, solver, time_limit)
        else:
            await flatten(interaction, self.message.content, solver, time_limit)


@app_commands.context_menu(name="Solve MiniZinc")
async def solve_menu(interaction: Interaction, message: Message):
    await interaction.response.send_modal(OptionModal(message, MZNAction.SOLVE))


@app_commands.context_menu(name="Flatten MiniZinc")
async def flatten_menu(interaction: Interaction, message: Message):
    await interaction.response.send_modal(OptionModal(message, MZNAction.FLATTEN))


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
        super().__init__(intents=intents)

        # Create tree object to add commands to
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.add_command(MZN())
        self.tree.add_command(solve_menu)
        self.tree.add_command(flatten_menu)
        await self.tree.sync()

    async def on_ready(self):
        print(
            f"{datetime.now().strftime('%H:%M:%S')} - {self.user} has connected to Discord!"
        )


if __name__ == "__main__":
    # Initialise Discord bot
    TOKEN = os.getenv("DISCORD_TOKEN")

    client = MZNClient()
    client.run(TOKEN)
