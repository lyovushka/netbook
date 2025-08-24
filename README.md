## About

A Jupyter notebook client for your terminal. 
It aims to emulate the functionality of the classic Jupyter notebook.
Built on the excellent [textual](https://github.com/Textualize/textual) framework with image support from [textual-image](https://github.com/lnqs/textual-image).

## Demo

![demo](./docs/images/demo.gif)

## Getting started

The easiest way to get started is with `uv`. To try without installing
```
uvx --from netbook jupyter-netbook [my_notebook.ipynb]
```

To install in the current virtual environment
```
uv pip install netbook
```

Or install it as a standalone tool
```
uv tool install netbook
```

Run it as follows
```
jupyter-netbook [my_notebook.ipynb]
```

## Terminal Support

| Terminal         | Status  | Image Support | Shift/Ctrl+Enter Support | Notes |
|------------------|---------|---------------|--------------------------|-------|
| Kitty            | ✅      | ✅ TGP        | ✅ Out of the box        | Remap some keybindings |
| Foot             | ✅      | ✅ Sixel      | ✅ Out of the box        | Sixel support is flaky |
| Contour          | ✅      | ✅ Sixel      | ✅ Out of the box        |       |
| ITerm2           | ✅      | ✅ Sixel      | ✅ Out of the box        | ITerm2 image protocal would probably be supported in the future |
| Wezterm          | ✅      | ✅ TGP        | ✅ Requires remapping    |       |
| Windows Terminal | ✅      | ✅ Sixel      | ✅ Requires remapping    | Things kind of work, sometimes... | 
| Ghosty           | 🤷      | ✅ TGP        | ✅ Out of the box        | I expect textual support of ghosty to improve |
| Alacritty        | 🤷      | ❌            | ✅ Requires remapping    | It is quite unlikely that alacritty will support images |
| Tmux             | 🤷      | ✅ Sixel      | 🤷 Not out of the box    | Not sure how to remap the key bindings |
| Zellij           | ❌      | ❌            | ✅ Out of the box        | Sixels seems to confuse it quite a bit

## Frequently asked questions

*Q:* Why are icons in the toolbar all jumbled up?

*A:* You need to have Font Awesome installed. Or you can download [nerd fonts](https://www.nerdfonts.com/) that already have the glyphs patched in.

*Q:* How can I start other kernels?

*A:* You can use `--kernel` argument. It accepts kernel names shown by `jupyter-kernelspec list`.

*Q*: How to see available keybindings?

*A:* Press 'h' in command mode (i.e. when focus is not in a text area). The keybindings are mostly compatible with the classic Jupyter notebook.

*Q:* How to remap the keys in my terminal?

*A:* Here are snippets for a selection of terminal emulators:

  - Kitty. Add the following to `~/.config/kitty/kitty.conf`
    ```
    # Send ctrl+shift+minus to netbook
    map --when-focus-on title:netbook kitty_mod+minus
    ```
  
  - Wezterm. Add the following to `~/.config/wezterm/wezterm.lua`
    ```
    local wezterm = require 'wezterm';

    return {
      -- ...

      keys = {
        {key="Enter", mods="CTRL", action=wezterm.action{SendString="\x1b[13;5u"}},
        {key="Enter", mods="SHIFT", action=wezterm.action{SendString="\x1b[13;2u"}},
        {key="Enter", mods="ALT", action=wezterm.action{SendString="\x1b[13;3u"}},
      },
    }
    ```
  - Windows Terminal. Add the following to `settings.json` file
    ```
    {
      // ...

      "keybindings":
      [
        { "command": { "action": "sendInput", "input": "\u001b[13;5u" }, "keys": "ctrl+enter" },
        { "command": { "action": "sendInput", "input": "\u001b[13;2u" }, "keys": "shift+enter" },
        { "command": { "action": "sendInput", "input": "\u001b[13;3u" }, "keys": "alt+enter" }
      ]
    }


Euporie, a related project, also has some [examples](https://euporie.readthedocs.io/en/latest/pages/keybindings.html),

## Development

To get set up just run
```
uv sync
uv run jupyter-netbook
```
