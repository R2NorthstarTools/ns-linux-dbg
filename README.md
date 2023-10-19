# NSDBG - Northstar Linux Debugger
a handy script to debug Northstar under Linux.

Flags:
- `--compat` chooses the compatibility layer to be used. Available are: `proton`(default), `wine`
- `--verbose` logs more information that may be useful when debugging nsdbg
- `--no-ea` opens a debugger without the EA Desktop app
- `--persist-ea` keeps the EA Desktop app open after the debugger closes

Arguments:
- `debugger` chooses which debugger to use. Available are: `winedbg`, `x64dbg`(recommended)
