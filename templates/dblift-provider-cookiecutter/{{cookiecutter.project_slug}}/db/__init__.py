# Empty on purpose for third-party provider template.
# The main 'dblift' package owns the real db/__init__.py and its exports.
# This file exists only so the source tree is a valid package layout for
# setuptools 'packages' declaration if ever needed; the actual distribution
# uses an explicit packages= list that avoids shipping a conflicting top-level.
