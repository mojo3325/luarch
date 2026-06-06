# Publish Checklist

Use this after reviewing the repository locally. The first GitHub push should stay private so the rendered README, release asset, and repository settings can be reviewed before making the repository public.

## GitHub

Recommended repository name:

```text
luarch
```

Recommended description:

```text
Procedural low-poly tactical building generator for Blender and game-engine workflows.
```

Recommended topics:

```text
blender
blender-addon
procedural-generation
game-development
low-poly
roblox
environment-art
python
```

## Private Review Publish

Recommended first publish:

```bash
gh repo create luarch --private --source . --remote origin --push
git branch -M main
git push --tags
```

Create a private GitHub release for review:

```text
Tag: v0.2.0
Title: LuArch v0.2.0
Asset: dist/luarch-v0.2.0.zip
```

## Before Public Submission

- [ ] README renders correctly in GitHub preview.
- [ ] `docs/media/plugin-icon.png` displays correctly.
- [ ] `docs/media/hero-wide.png` displays correctly.
- [ ] `docs/media/gallery-grid-3x3.png` displays correctly.
- [ ] Release zip is attached to a GitHub release.
- [ ] Release zip installs in Blender 4.5+.
- [ ] Repository settings, description, topics, and license detection are correct.
- [ ] No private local paths or private project names are present.
- [ ] No fake stars/downloads/users are claimed.

## Before Public Release

- [ ] Owner visually approves the private repository.
- [ ] Repository is switched from private to public.
- [ ] README renders correctly.
- [ ] `docs/media/hero-wide.png` displays correctly.
- [ ] `docs/media/gallery-grid-3x3.png` displays correctly.
- [ ] GitHub detects `GPL-3.0` license.
- [ ] Release zip is attached to a GitHub release.
- [ ] No fake stars/downloads/users are claimed.
