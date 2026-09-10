<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

The Lovable-managed frontend app lives in `frontend/`.

For backend, use uv for dependency management. A few useful commands:

uv sync
uv add <PACKAGE-NAME>
uv run python <PYTHON-FILE>

Regularly commit code to git.
