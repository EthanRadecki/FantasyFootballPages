"""Publish: analysis tables -> the site's data files, and `engine build`.

    writer.py       JSON-safe values, meta block, build id
    diff.py         section-by-section JSON comparison for Stage A checks
    config_json.py  config.json from league.yaml and the canonical tables
    site.py         the site template: its files and page list
    build.py        assemble and verify dist/
    pages/          one publisher per page
    schemas/        JSON schema for every page model file

See docs/PUBLISH_PLAN.md.
"""
