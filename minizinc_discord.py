from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import minizinc

import discord
from discord.ext import commands

# Initialise Discord bot
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(intents=intents, command_prefix="!")
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
    "Facticulating...",
    "Detonating in 3... 2... 1. Boom town.",
]


class OptionError(Exception):
    pass


class Option:
    __slots__ = ("key", "value")

    def __init__(self, key, value):
        self.key = key
        self.value = value

    @classmethod
    async def convert(cls, ctx, argument):
        arguments = argument.split("=")
        if len(arguments) != 2:
            raise commands.BadArgument("Invalid option")

        return cls(arguments[0], arguments[1])

    @staticmethod
    def process(options: List[Option], defaults: Dict[str, Any]) -> Dict[str, Any]:
        ret = defaults.copy()

        for option in options:
            if option.key == "solver":
                try:
                    ret["solver"] = minizinc.Solver.lookup(option.value)
                except LookupError:
                    raise OptionError(f'Solver "{option.value}" is not available')
            elif option.key == "timeout":
                if int(option.value) <= 30:
                    ret["timeout"] = timedelta(seconds=int(option.value))
                else:
                    raise OptionError(
                        "Timeout cannot be set to a value higher than 30 seconds"
                    )

        return ret

    def __repr__(self):
        return f'"{self.key}"="{self.value}"'


@bot.event
async def on_ready():
    print(
        f"{datetime.now().strftime('%H:%M:%S')} - {bot.user} has connected to Discord!"
    )


# Initialise MiniZinc
chuffed = minizinc.Solver.lookup("chuffed")
no_solver = minizinc.Solver("No Solver", "1.0.0", "com.discord.no_solver", "false")


# MiniZinc commands
@bot.command(name="version", help="Report the current MiniZinc version")
async def version(ctx):
    response = minizinc.default_driver.minizinc_version
    await ctx.send(response)


@bot.command(name="mzn", help="Run a MiniZinc instance")
async def mzn(ctx, options: commands.Greedy[Option], *, arg: str):
    response = await ctx.send(random.choice(running_messages))
    await ctx.message.add_reaction("⌛")

    arg = arg.strip("` \t")

    arguments = {
        "solver": chuffed,
        "timeout": timedelta(seconds=30),
    }

    try:
        arguments = Option.process(options, arguments)
        instance = minizinc.Instance(arguments["solver"])
        instance.add_string(arg)
        result = await instance.solve_async(timeout=arguments["timeout"])
        output = f"`{result.status}` in {result.statistics['time'].total_seconds()}s: {'```' + str(result.solution) + '```' if result.solution is not None else 'No Solution'}"
    except (OptionError, minizinc.MiniZincError) as err:
        output = "```" + str(err) + "```"

    await response.edit(content=output)
    await ctx.message.remove_reaction("⌛", bot.user)
    await ctx.message.add_reaction("✅")


@bot.command(name="flatten", help="Flatten a MiniZinc instance")
async def flatten(ctx, options: commands.Greedy[Option], *, arg: str):
    response = await ctx.send(random.choice(running_messages))
    await ctx.message.add_reaction("⌛")

    arg = arg.strip("` \t")

    arguments = {
        "solver": no_solver,
        "timeout": timedelta(seconds=30),
    }
    try:
        arguments = Option.process(options, arguments)
        instance = minizinc.Instance(arguments["solver"])
        instance.add_string(arg)
        with instance.flat(arguments["timeout"]) as (fzn, ozn, statistics):
            flatzinc = Path(fzn.name).read_text()
            output = f"```{flatzinc}```"
    except (OptionError, minizinc.MiniZincError) as err:
        output = "```" + str(err) + "```"

    await response.edit(content=output)
    await ctx.message.remove_reaction("⌛", bot.user)
    await ctx.message.add_reaction("✅")


bot.run(TOKEN)
