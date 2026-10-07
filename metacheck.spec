# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['metacheck_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('scripts/metacheck_report.R', 'scripts'), ('scripts/setup_r.R', 'scripts'), ('muecos_small.png', '.'), ('chetameck_logo_small.png', '.'), ('plagcheck_logo_small.png', '.'), ('metacheck_logo_small.png', '.'), ('muecos.ico', '.'), ('chetameck/modules/databases', 'chetameck/modules/databases')],
    hiddenimports=['updater', 'plagcheck', 'plagcheck.core', 'plagcheck.report', 'chetameck', 'chetameck.engine', 'chetameck.paper', 'chetameck.text', 'chetameck.report', 'chetameck.catalog', 'chetameck.descriptives', 'chetameck._log', 'chetameck.modules', 'chetameck.modules.registry', 'chetameck.modules._data', 'chetameck.modules._refs', 'chetameck.modules._online', 'chetameck.modules.all_p_values', 'chetameck.modules.all_urls', 'chetameck.modules.marginal', 'chetameck.modules.stat_p_exact', 'chetameck.modules.stat_p_nonsig', 'chetameck.modules.stat_check', 'chetameck.modules.stat_effect_size', 'chetameck.modules.es_check', 'chetameck.modules.coi_check', 'chetameck.modules.funding_check', 'chetameck.modules.ref_consistency', 'chetameck.modules.open_practices', 'chetameck.modules.power', 'chetameck.modules.repo_check', 'chetameck.modules.code_check', 'chetameck.modules.prereg_check', 'chetameck.modules.prereg_statement', 'chetameck.modules.ref_accuracy', 'chetameck.modules.ref_replication', 'chetameck.modules.ref_retraction', 'chetameck.modules.ref_pubpeer', 'chetameck.modules.ref_miscitation', 'chetameck.modules.ref_summary', 'chetameck.modules.forensic', 'chetameck.modules.r2_check', 'chetameck.modules.duplicate_check', 'chetameck.modules.image_forensic', 'chetameck.modules.df_consistency', 'chetameck.modules.affiliation_check', 'chetameck.modules.causal_language', 'chetameck.modules.reliability_check', 'chetameck.modules.irb_ethics_check', 'chetameck.modules.demographics_check', 'chetameck.modules.multiple_comparisons_check', 'chetameck.modules.exclusion_reporting_check', 'chetameck.modules.likert_parametric_check', 'chetameck.modules.interrater_reliability_check', 'chetameck.modules.harking_check', 'chetameck.modules.response_rate_check', 'chetameck.modules.missing_data_check', 'PIL', 'pymupdf', 'pandas', 'scipy', 'lxml', 'pyreadr'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ManuscriptChecker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['muecos.ico'],
)
