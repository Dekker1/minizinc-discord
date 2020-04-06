import os
from datetime import timedelta
from pathlib import Path

import minizinc

from discord.ext import commands

# Initialise Discord bot
TOKEN = os.getenv('DISCORD_TOKEN')
bot = commands.Bot(command_prefix='!')


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')


# Initialise MiniZinc
chuffed = minizinc.Solver.lookup("chuffed")
no_solver = minizinc.Solver("No Solver", "1.0.0", "com.discord.no_solver", "false")


# MiniZinc commands
@bot.command(name='version', help='Report the current MiniZinc version')
async def version(ctx):
    response = minizinc.default_driver.minizinc_version
    await ctx.send(response)


@bot.command(name='mzn', help='Run a MiniZinc instance')
async def mzn(ctx, instance: str):
    message = ctx.message.content
    assert message.startswith("!mzn ")
    message = message.replace("!mzn ", "", 1)
    message = message.strip("` \t")

    instance = minizinc.Instance(chuffed)
    instance.add_string(message)

    try:
        result = await instance.solve_async(timeout=timedelta(seconds=10))
        response = f"`{result.status}` in {result.statistics['time'].total_seconds()}s: {'No Solution' if result.solution is None else str(result.solution)}"
    except minizinc.MiniZincError as err:
        response = "```" + str(err) + "```"

    await ctx.send(response)


@bot.command(name='flatten', help='Flatten a MiniZinc instance')
async def mzn(ctx, instance: str):
    message = ctx.message.content
    assert message.startswith("!flatten ")
    message = message.replace("!flatten ", "", 1)
    message = message.strip("` \t")

    instance = minizinc.Instance(no_solver)
    instance.add_string(message)

    try:
        with instance.flat() as (fzn, ozn, statistics):
            flatzinc = Path(fzn.name).read_text()
            response = f"```{flatzinc}```"
    except minizinc.MiniZincError as err:
        response = "```" + str(err) + "```"

    await ctx.send(response)


bot.run(TOKEN)
