/* Deploy-time configuration. THE one place clip storage is named.
 *
 * COMPLIANCE.md, "Rules the code must respect": all clip URLs resolve from a
 * single CLIP_BASE_URL so storage can be swapped in one place. This is that
 * place. It is a committed file rather than an env var because the site is a
 * pure static deploy with no build step — nothing runs at request or build time
 * that could read the environment, and adding a build step to get one would
 * break an architectural constraint in CLAUDE.md for no gain. One file, one
 * line, one edit: the property the doc is actually asking for.
 *
 * TODAY it points at the committed clips, which is the arrangement COMPLIANCE.md
 * item 1 exists to end: the bytes are in git and served by Vercel. When they move
 * to R2, this becomes
 *
 *     CLIP_BASE: 'https://clips.gameover.fyi'
 *
 * and NOTHING else in the frontend changes. Only after that can *.mp4 enter
 * .gitignore — doing it in the other order takes the site down, because a
 * git-connected build only sees committed files.
 *
 * Trailing slash is normalised away by clipUrl(), so either form is safe here.
 */
window.GAMEOVER_CONFIG = {
  CLIP_BASE: '../clips',
};
