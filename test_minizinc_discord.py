"""Tests for the MiniZinc Discord bot

Run with `python -m unittest`, in an environment that has MiniZinc available.
The Discord objects the bot receives are faked, everything else is real.
"""

import asyncio
import doctest
import tempfile
import unittest
from pathlib import Path

import minizinc

import minizinc_discord as mzn

MODEL = 'include "helper.mzn";\nint: n;\nvar 1..n: x;\nconstraint dbl(x) > n;\nsolve satisfy;\noutput ["x=\\(x) n=\\(n)"];\n'
HELPER = "function var int: dbl(var int: y) = 2*y;\n"


class FakeAttachment:
    def __init__(self, filename: str, content: str, size: int | None = None):
        self.filename = filename
        self._content = content.encode()
        self.size = len(self._content) if size is None else size

    async def read(self) -> bytes:
        return self._content


class FakeMessage:
    def __init__(self, content: str = "", attachments=()):
        self.content = content
        self.attachments = list(attachments)


class FakeInteraction:
    """Records what the bot replies, in place of an actual Discord interaction"""

    def __init__(self):
        self.replies = []

    @property
    def response(self):
        return self

    @property
    def followup(self):
        return self

    async def defer(self, thinking: bool = False):
        pass

    async def send(self, content=None, file=None, ephemeral=False):
        self.replies.append((content, file))

    @property
    def text(self) -> str:
        return self.replies[0][0]

    @property
    def attachment(self):
        return self.replies[0][1]


def load_tests(loader, tests, ignore):
    """Run the doctests of the bot along with the tests below"""
    tests.addTests(doctest.DocTestSuite(mzn))
    return tests


class TestExtractCode(unittest.TestCase):
    def test_language_tag_is_not_code(self):
        self.assertEqual(
            mzn.extract_code("```mzn\nvar 1..3: x;\n```"), [(".mzn", "var 1..3: x;\n")]
        )

    def test_data_tags_are_data_files(self):
        self.assertEqual(
            mzn.extract_code("```minizinc\nint: n;\n```\n```dzn\nn = 4;\n```"),
            [(".mzn", "int: n;\n"), (".dzn", "n = 4;\n")],
        )
        self.assertEqual(
            mzn.extract_code('```json\n{"n": 4}\n```'), [(".json", '{"n": 4}\n')]
        )

    def test_message_without_fence_is_code(self):
        self.assertEqual(mzn.extract_code("`int: n;`"), [(".mzn", "int: n;")])
        self.assertEqual(mzn.extract_code("int: n;"), [(".mzn", "int: n;")])

    def test_fenced_only_ignores_surrounding_chatter(self):
        self.assertEqual(mzn.extract_code("can you solve this?", fenced_only=True), [])
        self.assertEqual(
            mzn.extract_code("look:\n```\nint: n;\n```\nthanks!", fenced_only=True),
            [(".mzn", "int: n;\n")],
        )

    def test_empty_blocks_are_dropped(self):
        self.assertEqual(mzn.extract_code("```\n\n```"), [])
        self.assertEqual(mzn.extract_code(""), [])


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Running MiniZinc blocks for a moment, which is not worth warning about
        asyncio.get_running_loop().set_debug(False)


class TestInstanceFiles(BotTestCase):
    async def files_of(self, message) -> list[str]:
        async with mzn.instance_files(message) as files:
            return sorted(file.name for file in files)

    async def test_code_blocks_become_files(self):
        names = await self.files_of(
            FakeMessage("```mzn\nint: n;\n```\n```dzn\nn = 4;\n```")
        )
        self.assertEqual(names, ["message0.mzn", "message1.dzn"])

    async def test_attachments_are_used(self):
        names = await self.files_of(
            FakeMessage("please solve", [FakeAttachment("model.mzn", "var 1..3: x;")])
        )
        self.assertEqual(names, ["model.mzn"], "chatter must not become a model")

    async def test_included_files_are_not_added_twice(self):
        names = await self.files_of(
            FakeMessage(f"```mzn\n{MODEL}```", [FakeAttachment("helper.mzn", HELPER)])
        )
        self.assertEqual(names, ["message0.mzn"], "helper.mzn is included by the model")

    async def test_only_minizinc_files_are_accepted(self):
        names = await self.files_of(
            FakeMessage(
                "```mzn\nvar 1..3: x;\n```",
                [FakeAttachment("virus.exe", "x"), FakeAttachment("notes.txt", "y")],
            )
        )
        self.assertEqual(names, ["message0.mzn"])

    async def test_oversized_attachments_are_skipped(self):
        names = await self.files_of(
            FakeMessage(
                "```mzn\nvar 1..3: x;\n```",
                [FakeAttachment("big.dzn", "n = 1;", size=mzn.MAX_ATTACHED + 1)],
            )
        )
        self.assertEqual(names, ["message0.mzn"])

    async def test_attachment_cannot_escape_the_directory(self):
        async with mzn.instance_files(
            FakeMessage("", [FakeAttachment("../../../etc/evil.dzn", "n = 1;")])
        ) as files:
            self.assertEqual([file.name for file in files], ["evil.dzn"])
            self.assertEqual(files[0].parent.parent, Path(tempfile.gettempdir()))

    async def test_directory_is_removed(self):
        async with mzn.instance_files(FakeMessage("var 1..3: x;")) as files:
            directory = files[0].parent
            self.assertTrue(directory.exists())
        self.assertFalse(directory.exists())

    async def test_directory_is_removed_after_failure(self):
        with self.assertRaises(RuntimeError):
            async with mzn.instance_files(FakeMessage("var 1..3: x;")) as files:
                directory = files[0].parent
                raise RuntimeError("boom")
        self.assertFalse(directory.exists())


class TestCheckModel(BotTestCase):
    async def warning_for(self, message) -> str | None:
        async with mzn.instance_files(message) as files:
            return mzn.check_model(files)

    async def test_valid_fragment(self):
        self.assertIsNone(
            await self.warning_for(FakeMessage("```mzn\nvar 1..3: x;\n```"))
        )

    async def test_model_and_data_split_over_blocks(self):
        message = FakeMessage("```mzn\nint: n;\nvar 1..n: x;\n```\n```dzn\nn = 4;\n```")
        self.assertIsNone(await self.warning_for(message))

    async def test_syntax_error(self):
        warning = await self.warning_for(FakeMessage("```mzn\nvar 1..3 x;\n```"))
        self.assertIn("syntax error", warning)

    async def test_undefined_identifier(self):
        warning = await self.warning_for(FakeMessage("```mzn\nconstraint y > 2;\n```"))
        self.assertIn("undefined identifier", warning)

    async def test_message_without_code(self):
        warning = await self.warning_for(FakeMessage(""))
        self.assertIn("does not contain any MiniZinc code", warning)


class TestActions(BotTestCase):
    async def act(self, action, message, solver=None):
        interaction = FakeInteraction()
        async with mzn.instance_files(message) as files:
            await action(interaction, files, solver or mzn.no_solver, 10)
        return interaction

    async def test_solve_uses_data_from_a_second_block(self):
        interaction = await self.act(
            mzn.solve,
            FakeMessage(
                '```mzn\nint: n;\nvar 1..n: x;\nconstraint x > 2;\nsolve satisfy;\noutput ["x=\\(x)"];\n```\n```dzn\nn = 5;\n```'
            ),
            minizinc.Solver.lookup("gecode"),
        )
        self.assertIn("x=3", interaction.text)
        self.assertIn("SATISFIED", interaction.text)

    async def test_solve_uses_an_attached_include(self):
        interaction = await self.act(
            mzn.solve,
            FakeMessage(
                f"```mzn\n{MODEL}```\n```dzn\nn = 6;\n```",
                [FakeAttachment("helper.mzn", HELPER)],
            ),
            minizinc.Solver.lookup("gecode"),
        )
        self.assertIn("x=4 n=6", interaction.text)

    async def test_flatten(self):
        interaction = await self.act(
            mzn.flatten, FakeMessage("```mzn\nvar 1..3: x;\nconstraint x > 2;\n```")
        )
        self.assertIn("FlatZinc", interaction.text)
        self.assertIn("Generated by MiniZinc", interaction.text)
        self.assertIn("solve", interaction.text)

    async def test_error_is_reported(self):
        interaction = await self.act(
            mzn.solve,
            FakeMessage("```mzn\nconstraint y > 2;\n```"),
            minizinc.Solver.lookup("gecode"),
        )
        self.assertIn("undefined identifier", interaction.text)

    async def test_long_output_is_attached_as_a_file(self):
        interaction = await self.act(
            mzn.flatten,
            FakeMessage(
                "```mzn\narray[1..2000] of var 1..9: x;\nconstraint forall(i in 1..1999)(x[i] <= x[i+1]);\nsolve satisfy;\n```"
            ),
        )
        self.assertEqual(interaction.attachment.filename, "model.fzn")
        self.assertGreater(len(interaction.attachment.fp.getvalue()), 1800)

    async def test_replies_stay_within_the_discord_limit(self):
        for content in ["```mzn\nvar 1..3: x;\n```", "```mzn\nvar 1..3 x;\n```"]:
            interaction = await self.act(mzn.flatten, FakeMessage(content))
            self.assertLess(len(interaction.text), 2000)


class TestOptionModal(BotTestCase):
    async def test_solver_menu(self):
        modal = await mzn.OptionModal.create(
            FakeMessage("```mzn\nvar 1..3: x;\n```"), mzn.MZNAction.SOLVE
        )
        components = modal.to_dict()["components"]
        self.assertLessEqual(len(components), 5, "a modal holds at most 5 components")
        select = next(c["component"] for c in components if c["component"]["type"] == 3)
        self.assertLessEqual(len(select["options"]), 25, "Discord shows at most 25")
        self.assertTrue(any(option.get("default") for option in select["options"]))
        self.assertNotIn(10, [c["type"] for c in components], "no warning expected")

    async def test_flatten_offers_the_standard_library(self):
        modal = await mzn.OptionModal.create(
            FakeMessage("```mzn\nvar 1..3: x;\n```"), mzn.MZNAction.FLATTEN
        )
        select = next(
            c["component"]
            for c in modal.to_dict()["components"]
            if c["component"]["type"] == 3
        )
        default = next(o for o in select["options"] if o.get("default"))
        self.assertEqual(default["value"], mzn.STDLIB)

    async def test_broken_model_is_shown_as_a_warning(self):
        modal = await mzn.OptionModal.create(
            FakeMessage("```mzn\nvar 1..3 x;\n```"), mzn.MZNAction.SOLVE
        )
        components = modal.to_dict()["components"]
        self.assertEqual(components[0]["type"], 10, "warning goes above the options")
        self.assertIn("syntax error", components[0]["content"])
        self.assertEqual(
            len(components), 3, "the options are still there, so the user can continue"
        )


if __name__ == "__main__":
    unittest.main()
