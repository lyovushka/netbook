## About

A Jupyter notebook client for your terminal.
Built on the excellent [textual](https://github.com/Textualize/textual) framework with image support from [textual-image](https://github.com/lnqs/textual-image).

## Demo

![demo](./docs/images/demo.gif)

## Getting started

```
pip install netbook
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

*Q:* How to remap the keys in my terminal?

*A:* Euporie, a related project, has some [examples](https://euporie.readthedocs.io/en/latest/pages/keybindings.html)

## Development

You need to have [uv](https://docs.astral.sh/uv/) installed. To get set up just run

```
uv sync
uv run jupyter-netbook
```
