# software-engineering-tuwien.github.io

Course websites for TU Wien's software engineering project courses:

| Course | Number | Level | URL |
| --- | --- | --- | --- |
| Software Engineering Projekt | 194.148 | Bachelor | <https://software-engineering-tuwien.github.io/sep/> |
| Advanced Software Engineering | 188.910 | Master | <https://software-engineering-tuwien.github.io/ase/> |

## How this is deployed

GitHub Pages serves this repository directly from the `main` branch, root path
("deploy from a branch"). There is **no** Actions workflow and no local build step:
pushing to `main` publishes the site within a minute or two.

GitHub runs Jekyll server-side on every push (the Pages API calls this build type
`legacy`, meaning branch-based deployment rather than a GitHub Actions workflow &mdash; not
an outdated Jekyll). It pins Jekyll 3.x via the `github-pages` gem and allows only
whitelisted plugins, so custom Ruby plugins will not run.

Jekyll is used here only as a templating engine so the two courses cannot drift apart
&mdash; shared boilerplate lives in `_layouts/` and `_includes/`, everything course-specific
is hand-written HTML.

> **Do not add a `.nojekyll` file.** It would disable the includes and the pages would
> render with their `---` front matter visible as literal text.

## Layout

```
index.html              Landing page linking to both courses
sep/index.html          Redirects to the current SEP edition + archive list
sep/2026W/index.html    Software Engineering Projekt, WS 2026/27
ase/index.html          Redirects to the current ASE edition + archive list
ase/2026W/index.html    Advanced Software Engineering, WS 2026/27
slides/                 PDFs, shared across both courses and all editions
_layouts/base.html      <head>, water.css, inline CSS, footer
_layouts/default.html   Plain page shell (landing + archive pages)
_layouts/course.html    Course page shell: header, anchor nav, and the two shared
                        policy sections appended after the page content
_includes/              Shared prose: AI policy, academic honesty
```

Styling is [water.css](https://watercss.kognise.dev/) loaded from a CDN &mdash; it is
classless, so semantic HTML renders well without any classes. Course-specific CSS
(nav separators, the mobile table collapse) lives in `_layouts/base.html`.

## Bootstrapping course data from TISS

Teaching staff, registration periods, and dates can be pulled from TISS by a script to avoid duplicate effort. The script is intended to be run just once to generate the initial data YAML file `_data/courses/<course>/<semester>.yml`, which the pages read as `site.data.courses[page.course][page.semester]`:

```bash
python3 tools/fetch_tiss.py 2026W
```

Add `--course sep` (or `ase`) to do just one.

Once generated, the YAML file is explicitly intended to be modified and changed by hand to fill in details or make course-specific adjustments. Everything else on the pages is hand-written.

## Adding a new edition

1. Copy the most recent edition folder, e.g. `cp -r sep/2026W sep/2027S`.
2. Update the front matter in the new `index.html`: `edition`, `title`, and the
   `semester=` parameter of the `tiss` URL (`2027S`, `2027W`, ...).
3. Update the page body: team, timetable, assignments, grading.
4. Point `redirect_to` in `sep/index.html` at the new folder and add the previous
   edition to that page's archive list.
5. Update the "current edition" links on the root `index.html`.

Previous editions stay online at their original URLs and are never edited again.

## Page language

Each course page declares its language in front matter:

```yaml
lang: de   # omit, or use `en`, for English pages
```

This sets `<html lang>` and switches the section labels in the navigation. Section
anchors (`#team`, `#registration`, ...) stay in English in every language so links
keep working across editions.

Currently: **SEP is German** (the course is taught in German), **ASE is English**.

The shared `_includes/` (AI usage policy, academic honesty) are **English on every
page**, and carry an explicit `lang="en"` so screen readers switch voice correctly on
the German page. Their headings are therefore also English in the navigation.

## Editing shared content

The AI usage policy and the academic honesty statement are the same for both courses.
(Prerequisites are *not* shared — they differ per course and live in the course pages.) Edit them once in `_includes/` &mdash; the change applies to every page that
includes them, including past editions. If a past edition must keep its original
wording, inline that text into the edition's own `index.html` before changing the include.

## Local preview (optional)

Not required &mdash; you can push and check the live site. If you want a local preview:

```bash
gem install bundler jekyll && jekyll serve
```

## Placeholders

Unwritten content is marked with a yellow `TODO` badge in the rendered page. Search for
`class="todo"` to find everything that still needs filling in.
