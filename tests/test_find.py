import textual.pilot
import netbook._textual_app


async def test_find(pilot_nb: textual.pilot.Pilot):
    app: netbook._textual_app.JupyterTextualApp = pilot_nb.app
    assert app.find.hidden
    await pilot_nb.press("escape", "f")
    await pilot_nb.pause()
    assert not app.find.hidden

    await pilot_nb.press(*list(".Display"))
    await pilot_nb.pause()
    assert app.find.text.content == " 1 of 2 "

    await pilot_nb.press("enter")
    await pilot_nb.pause()
    assert app.find.text.content == " 2 of 2 "

    await pilot_nb.press("shift+enter")
    await pilot_nb.pause()
    assert app.find.text.content == " 1 of 2 "

    await pilot_nb.click(app.find.regular_expression)
    await pilot_nb.pause()
    assert app.find.text.content == " 1 of 3 "

    # Test malformed regular expression
    await pilot_nb.press("[")
    await pilot_nb.pause()
    assert app.find.text.content == "Not Found"

    # Change back
    await pilot_nb.press("backspace")
    await pilot_nb.pause()
    assert app.find.text.content == " 1 of 3 "

    await pilot_nb.click(app.find.whole_word)
    await pilot_nb.pause()
    assert app.find.text.content == " 1 of 2 "

    await pilot_nb.click(app.find.match_case)
    await pilot_nb.pause()
    assert app.find.text.content == "Not Found"

    await pilot_nb.press("escape")
    await pilot_nb.pause()
    assert app.find.hidden
