# Attribution — handraw-style data

The style / layout / theme-color data in `handraw_index.json` (this
directory) was extracted from the open-source project
**handraw-style** by **yang0**:

- Upstream repository: https://github.com/yang0/handraw-style
- Upstream version extracted: 1.9.1
- License: MIT License with Attribution Requirement (full text in
  `LICENSE` in this directory)

Per the upstream license: free to use, modify, distribute and
commercialize; when this data (or a product based on it) is used, credit
to the original author **yang0** and the original repository link
(https://github.com/yang0/handraw-style) must be retained and clearly
displayed in documentation, repository, product description, or user
interface. This file, the license header in `handraw_index.json`, and
the `attribution` field written into every `image.styled_generate`
sidecar satisfy that requirement on the hevi side.

Rebuild the index from a fresh upstream checkout with:

```
HEVI_HANDRAW_HOME=~/projects/_refs/handraw-style \
    python3 build_handraw_index.py
```
