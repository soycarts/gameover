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
 * It now points at the R2 bucket, which is what COMPLIANCE.md item 1 asked for:
 * the bytes are served by Cloudflare, not by the deployment. Nothing else in the
 * frontend changed to get here — this one line is the whole switch, which is the
 * property the single-CLIP_BASE_URL rule exists to buy.
 *
 * The clips are STILL committed and still inside the Vercel bundle at this point,
 * so reverting this line restores the old arrangement exactly. That safety net
 * disappears at the next step: *.mp4 entering .gitignore and clips/ entering
 * .vercelignore. Doing THAT before this line was flipped would have taken the
 * site down, because a git-connected build only sees committed files.
 *
 * Trailing slash is normalised away by clipUrl(), so either form is safe here.
 */
window.GAMEOVER_CONFIG = {
  CLIP_BASE: 'https://clips.gameover.fyi',
};
