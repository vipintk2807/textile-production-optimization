# Publishing to GitHub (account `vipintk2807`, repository `textile-production-optimization`)

Nothing here has been done for you: the repository was **not** created and nothing was pushed.
You use several GitHub accounts, so verify each item before pushing. Never paste passwords, tokens or private keys anywhere.

## 0. One-time: create the empty repository
On github.com, signed in as **vipintk2807**, create `textile-production-optimization` (public or private) with **no** README/.gitignore/licence (the project already has them).

## 1. Extract and open the folder (CMD)
```bat
cd path\to\textile-production-optimization
dir
```
Confirm you see `app.py`, `src`, `tests`, `README.md`. The ZIP contains **no** private planning documents or `master_prompt.md`.

## 2. Initialise Git with a repository-local identity (does not change global settings)
```bat
git init -b main
git config --local user.name "Vipin T K"
git config --local user.email "YOUR-EMAIL-FOR-THE-vipintk2807-ACCOUNT"
git config --local --list | findstr /i "user. remote"
```
(If `-b` is unsupported by an old Git: `git init` then `git branch -M main`.) Use the email that is verified on the vipintk2807 account (or its GitHub `noreply` address).

## 3. Check the SSH alias before using it
```bat
type %USERPROFILE%\.ssh\config
```
Look for a `Host github-vipintk2807` block whose `HostName` is `github.com` and whose `IdentityFile` is the key registered on the **vipintk2807** account. Then:
```bat
ssh -T git@github-vipintk2807
```
Expected: `Hi vipintk2807! You've successfully authenticated...`. If it names a different user, **stop** and fix the alias (do not push). If the alias does not exist, do not invent one; use HTTPS with the browser/Git Credential Manager sign-in as `vipintk2807` instead:
`https://github.com/vipintk2807/textile-production-optimization.git`.

## 4. Add the remote and verify it
```bat
git remote add origin git@github-vipintk2807:vipintk2807/textile-production-optimization.git
git remote -v
git ls-remote origin
```
`git ls-remote` only reads; an empty result for a new empty repository is normal. The URL must contain `vipintk2807/textile-production-optimization`.

## 5. Check what will be published
```bat
git status
git add .
git status
```
Make sure no `.db`, `.venv`, `data\logs`, `.env`, key files or planning documents are staged (they are in `.gitignore`).

## 6. Commit, confirm branch, push
```bat
git commit -m "Initial release: textile production optimization (v0.1.0)"
git branch --show-current
git push -u origin main
```
Confirm on github.com that the repository belongs to `vipintk2807` and the files appear.

## Keep private planning documents separate
Your planning files belong in the separate private repository `textile-production-optimization-planning`; do not copy them into this folder.
