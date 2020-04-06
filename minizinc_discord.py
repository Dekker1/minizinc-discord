import os
import random
from datetime import timedelta
from pathlib import Path

import minizinc

from discord.ext import commands

# Initialise Discord bot
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(command_prefix="!")
running_messages = [
    "Commencing infinite loop...",
    "The Constraint Elders are contemplating your request...",
    "Generating random numbers ...er... I mean solving! Yeah, solving...",
    "Sacrificing a resistor to the machine gods...",
    "Programming the flux capacitor...",
    "Compiling Gecode. Sit back and relax...",
    "Constructing additional pylons...",
    "Proving P=NP...",
    "Work, work...",
]


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")


# Initialise MiniZinc
chuffed = minizinc.Solver.lookup("chuffed")
no_solver = minizinc.Solver("No Solver", "1.0.0", "com.discord.no_solver", "false")


# MiniZinc commands
@bot.command(name="version", help="Report the current MiniZinc version")
async def version(ctx):
    response = minizinc.default_driver.minizinc_version
    await ctx.send(response)


@bot.command(name="mzn", help="Run a MiniZinc instance")
async def mzn(ctx, *, arg: str):
    response = await ctx.send(random.choice(running_messages))
    await ctx.message.add_reaction("⌛")

    arg = arg.strip("` \t")
    instance = minizinc.Instance(chuffed)
    instance.add_string(arg)

    try:
        result = await instance.solve_async(timeout=timedelta(seconds=30))
        output = f"`{result.status}` in {result.statistics['time'].total_seconds()}s: {'No Solution' if result.solution is None else str(result.solution)}"
    except minizinc.MiniZincError as err:
        output = "```" + str(err) + "```"

    await response.edit(content=output)
    await ctx.message.remove_reaction("⌛", bot.user)
    await ctx.message.add_reaction("✅")


@bot.command(name="flatten", help="Flatten a MiniZinc instance")
async def mzn(ctx, *, arg: str):
    response = await ctx.send(random.choice(running_messages))
    await ctx.message.add_reaction("⌛")

    arg = arg.strip("` \t")
    instance = minizinc.Instance(no_solver)
    instance.add_string(arg)

    try:
        with instance.flat() as (fzn, ozn, statistics):
            flatzinc = Path(fzn.name).read_text()
            output = f"```{flatzinc}```"
    except minizinc.MiniZincError as err:
        output = "```" + str(err) + "```"

    await response.edit(content=output)
    await ctx.message.remove_reaction("⌛", bot.user)
    await ctx.message.add_reaction("✅")


bot.run(TOKEN)
