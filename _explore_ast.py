"""Temporary script to explore tree-sitter AST structures for new languages."""
import sys

def show_ast(code, parser, max_depth=6):
    tree = parser.parse(code)
    types = set()
    def show(node, indent=0):
        if indent > max_depth: return
        extra = ''
        if node.type in ('simple_identifier', 'type_identifier', 'identifier'):
            extra = ' = ' + code[node.start_byte:node.end_byte].decode('utf-8','replace')
        print(' ' * indent + node.type + ' [L' + str(node.start_point[0]+1) + ']' + extra)
        types.add(node.type)
        for c in node.children:
            show(c, indent+2)
    show(tree.root_node)
    return types

# --- Kotlin ---
print("=" * 60)
print("KOTLIN AST")
print("=" * 60)
import tree_sitter_kotlin as tsk
from tree_sitter import Language, Parser
KOTLIN = Language(tsk.language())
kparser = Parser(KOTLIN)
code = open(r'W:\git\Bladed\.teamcity\ProjectFactory.kt', 'rb').read()
kt_types = show_ast(code, kparser)
print("\nAll Kotlin node types:", sorted(kt_types))

# --- PowerShell ---
print("\n" + "=" * 60)
print("POWERSHELL AST")
print("=" * 60)
import tree_sitter_powershell as tsps
PS_LANG = Language(tsps.language())
psparser = Parser(PS_LANG)
code2 = open(r'W:\git\Bladed\Build\VirtualBoxScripts\VBoxHelpers.ps1', 'rb').read()
ps_types = show_ast(code2, psparser)
print("\nAll PowerShell node types:", sorted(ps_types))
