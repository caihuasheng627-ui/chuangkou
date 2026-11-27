window.__ModuleLoader__.load({
  id: 'dsh-wound-clinic',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const NS = 'wound-clinic';

    const en = { open: 'Wound Clinic', subtitle: 'Thermal screening workspace', close: 'Close' };
    const zh = { open: '创口工作站', subtitle: '热成像辅助筛查', close: '关闭' };

    const DEMO = {
      schema_version: '1.0', measurement_id: 'MEAS-DEMO-0001', patient_ref: 'DEMO-001',
      encounter_id: 'ENC-DEMO-0001', captured_at: '2026-11-23T10:25:38+08:00',
      device: { model: 'HM-TB421-3XF', capture_mode: 'mock_y16', emissivity: 0.98, distance_m: 0.4, ambient_c: 24,
        calibration: { status: 'valid', calibration_id: 'CAL-DEMO-001' } },
      quality: { frames_used: 30, temporal_median_frames: 5, roi_valid: true, reference_valid: true,
        temperature_in_range: true, roi_method: 'automatic_hotspot', warnings: ['模拟数据，仅用于界面与接口演示'] },
      metrics: { t_wound_mean_c: 34.79, t_ref_far_c: 32.51, t_ref_near_c: 32.93,
        delta_t_c: 2.28, t_wound_max_c: 37.96, area_ratio: 0.112, gradient_c: 3.17 },
      thresholds: { version: 'wound-delta-v1', normal_max_c: 0.6, warning_max_c: 2.2, infection_min_c: 2.55 },
    };

    const EVIDENCE = [
      { id: 'E002', year: 2023, type: '诊断队列', title: 'Is my wound infected? Thermal asymmetry and bacterial fluorescence',
        text: '创周热不对称 ≥2.55°C 用于区分感染与非感染伤口；研究中敏感度 100%、特异度 64%，不能替代病原学。',
        scope: '研究纳入的慢性创口人群，不能外推为所有伤口的通用确诊界值。',
        url: 'https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2023.1165281/pdf' },
      { id: 'E003', year: 2007, type: '随机对照试验', title: 'Preventing Diabetic Foot Ulcer Recurrence in High-Risk Patients',
        text: '双侧对应位点温差 >2.2°C 用于糖尿病足居家预警和复测流程。',
        scope: '糖尿病足溃疡复发高风险人群，不是所有创口的感染诊断阈值。',
        url: 'http://secureservercdn.net/184.168.47.225/38d.2c6.myftpupload.com/wp-content/uploads/2015/07/Preventing-Diabetic-Foot-Ulcer-Diabetes-Care-2007.pdf' },
      { id: 'E004', year: 2024, type: '临床证据', title: 'Repeated temperature assessment and screening limitations',
        text: '单次温度筛查存在假阳性，重复测量与趋势确认优于单次读数。',
        scope: '用于支持复测建议，不用于单独确诊或排除感染。',
        url: 'https://www.ovid.com/journals/jlex/abstract/10.1177/15347346211062719' },
      { id: 'E001', year: 2021, type: '范围综述', title: 'What is the normal wound bed temperature?',
        text: '慢性非感染伤口床 30.2–33.0°C 是综述提出的参考范围/假说。',
        scope: '绝对温度受部位、环境和血流影响，仅作辅助参考。',
        url: 'https://aka.doubaocdn.com/l/Ta0ZUXXgVH' },
    ];

    const C = {
      teal: '#0f766e', tealSoft: '#e6f4f1', ink: '#172b35', muted: '#647780',
      line: '#dce5e8', bg: '#f3f6f7', white: '#ffffff', orange: '#c2410c',
      orangeSoft: '#fff4e8', navy: '#101c24', blue: '#2563eb', red: '#b42318',
    };
    const TABS = [['screen', '实时筛查'], ['reports', '报告中心'], ['archive', '患者档案'], ['trend', '随访趋势'], ['evidence', '医学知识库']];
    const DETAIL_LABELS = { site: '创口部位', duration: '病程 / 持续时间', symptoms: '创面表现', treatment: '处理与用药史', notes: '其他备注' };
    const fmtDelta = (value) => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}°C` : '—';
    const fmtTime = (value) => String(value || '').replace('T', ' ').slice(0, 16) || '-';
    const fieldInput = { width: '100%', boxSizing: 'border-box', padding: '8px 10px', border: `1px solid ${C.line}`, borderRadius: 8,
      font: '12px/18px system-ui,"Microsoft YaHei",sans-serif', color: C.ink, outline: 'none', background: '#fff' };
    const S = {
      launcher: { position: 'fixed', right: 20, bottom: 64, zIndex: 42, display: 'flex', alignItems: 'center', gap: 9,
        padding: '10px 16px', border: '1px solid rgba(255,255,255,.12)', borderRadius: 12,
        background: 'linear-gradient(135deg,#132630,#0e1c24)', color: '#fff', boxShadow: '0 10px 30px rgba(10,25,32,.22)', cursor: 'pointer',
        font: '13px/18px system-ui,"Microsoft YaHei",sans-serif', fontWeight: 600 },
      mask: { position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(7,18,24,.64)', backdropFilter: 'blur(7px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
      app: { width: 'min(1440px,97vw)', height: 'min(900px,94vh)', background: C.bg, borderRadius: 18,
        overflow: 'hidden', boxShadow: '0 32px 100px rgba(0,0,0,.34)', display: 'flex', flexDirection: 'column',
        font: '13px/20px system-ui,"Microsoft YaHei",sans-serif', color: C.ink },
      header: { height: 72, flex: '0 0 auto', background: 'linear-gradient(110deg,#101f28,#132933)', color: '#fff', display: 'flex', alignItems: 'center',
        padding: '0 24px', gap: 14, borderBottom: '1px solid rgba(255,255,255,.07)' },
      body: { display: 'flex', minHeight: 0, flex: 1 },
      nav: { width: 198, flex: '0 0 auto', background: '#fbfcfc', borderRight: `1px solid ${C.line}`, padding: '22px 14px' },
      main: { flex: 1, minWidth: 0, overflow: 'auto', padding: '24px 26px', background: 'linear-gradient(180deg,#f7f9fa,#f1f5f6)' },
      card: { background: C.white, border: `1px solid ${C.line}`, borderRadius: 14, padding: 17,
        boxShadow: '0 2px 6px rgba(21,46,56,.025)' },
      button: { border: `1px solid ${C.line}`, borderRadius: 9, padding: '8px 13px', background: '#fff',
        color: C.ink, cursor: 'pointer', font: '12px/18px system-ui,"Microsoft YaHei",sans-serif', fontWeight: 600,
        boxShadow: '0 1px 2px rgba(21,46,56,.03)' },
      primary: { border: `1px solid ${C.teal}`, borderRadius: 9, padding: '8px 14px', background: 'linear-gradient(135deg,#0f766e,#0b655f)',
        color: '#fff', cursor: 'pointer', font: '12px/18px system-ui,"Microsoft YaHei",sans-serif', fontWeight: 600,
        boxShadow: '0 4px 10px rgba(15,118,110,.14)' },
      label: { color: C.muted, fontSize: 11, letterSpacing: '.035em', fontWeight: 550 },
      value: { fontSize: 25, fontWeight: 720, fontVariantNumeric: 'tabular-nums', lineHeight: '31px', letterSpacing: '-.02em' },
      muted: { color: C.muted },
    };

    function Logo() {
      return h('div', { style: { width: 38, height: 38, borderRadius: 11, background: 'linear-gradient(135deg,#129184,#0f766e)', display: 'grid', placeItems: 'center',
        fontSize: 23, fontWeight: 300, color: '#fff', boxShadow: '0 5px 16px rgba(15,118,110,.25)' } }, '+');
    }
    function Icon({ name, size = 17 }) {
      const paths = {
        screen: 'M3 4h18v12H3z M8 20h8 M12 16v4',
        archive: 'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
        trend: 'M4 19V5 M4 19h16 M7 15l4-4 3 2 5-7',
        reports: 'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7',
        evidence: 'M12 2l8 3v6c0 5-3 8-8 11-5-3-8-6-8-11V5z M8 11l2 2 5-5',
        expand: 'M8 3H3v5 M16 3h5v5 M8 21H3v-5 M16 21h5v-5',
        collapse: 'M3 8h5V3 M21 8h-5V3 M3 16h5v5 M21 16h-5v5',
        close: 'M6 6l12 12 M18 6L6 18',
        assistant: 'M21 11.5a8.5 8.5 0 0 1-12.3 7.6L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z M8 11h8 M8 15h5',
        send: 'M4 12l16-8-6 16-3-7z',
        panelClose: 'M9 5l7 7-7 7',
      };
      return h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
        strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true },
        h('path', { d: paths[name] || paths.screen }));
    }
    // 兼容两种调用：Badge({ tone }, '文字') 直接调用，或 h(Badge, { tone }, '文字')。
    function Badge(props, ...children) {
      const { tone = 'teal' } = props || {};
      const content = children.length ? (children.length === 1 ? children[0] : children) : (props && props.children);
      const map = { teal: [C.tealSoft, C.teal], orange: [C.orangeSoft, C.orange], gray: ['#edf2f4', C.muted] };
      const [bg, color] = map[tone] || map.gray;
      return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 8px', borderRadius: 6,
        background: bg, color, fontSize: 11, fontWeight: 650, whiteSpace: 'nowrap' } }, content);
    }
    function Button(children, onClick, primary = false, extra = {}) {
      return h('button', { onClick, style: { ...(primary ? S.primary : S.button), ...extra } }, children);
    }
    function SectionTitle(title, subtitle, right) {
      return h('div', { style: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 14 } },
        h('div', null, h('div', { style: { fontSize: 15, fontWeight: 700 } }, title),
          subtitle && h('div', { style: { ...S.muted, fontSize: 11, marginTop: 2 } }, subtitle)), right);
    }
    function Metric(label, value, unit, note, accent) {
      const code = label.includes('温差') ? 'ΔT' : label.includes('面积') ? 'A' : label.includes('参考') ? 'R' : 'W';
      return h('div', { style: { ...S.card, padding: '15px 16px', minWidth: 0, position: 'relative', overflow: 'hidden' } },
        h('div', { style: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: accent || '#c9d9dd' } }),
        h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } },
          h('div', { style: S.label }, label),
          h('span', { style: { width: 26, height: 26, borderRadius: 8, display: 'grid', placeItems: 'center',
            background: accent ? C.orangeSoft : '#eef4f5', color: accent || C.muted, fontSize: 10, fontWeight: 750 } }, code)),
        h('div', { style: { ...S.value, color: accent || C.ink, marginTop: 7 } }, value,
          h('span', { style: { fontSize: 12, fontWeight: 500, marginLeft: 5, color: C.muted, letterSpacing: 0 } }, unit)),
        note && h('div', { style: { fontSize: 10, color: C.muted, marginTop: 5 } }, note));
    }
    const SOURCE_LABEL = { y16: 'Y16 原始温度', color: '伪彩视频 · 无温度', mock: '模拟数据源', none: '无数据源' };
    function liveBadge(st) {
      if (!st) return { tone: 'gray', text: '摄像头未连接' };
      if (st.source === 'y16' && st.has_temperature) return { tone: 'teal', text: 'Y16 · 实时温度' };
      if (st.source === 'y16') return { tone: 'orange', text: 'Y16 · 未标定' };
      if (st.source === 'color') return { tone: 'orange', text: '伪彩视频 · 无温度' };
      if (st.source === 'mock') return { tone: 'gray', text: '模拟数据源' };
      return { tone: 'gray', text: SOURCE_LABEL[st.source] || st.source };
    }
    function LiveThermal({ live, liveOn, stamp, busy, error, cfg, onCfgChange, onApplyCfg, onConnect, onDisconnect, onCapture, onEngine }) {
      const badge = liveBadge(live);
      const temps = (live && live.temperatures) || null;
      return h('div', { style: { ...S.card, background: C.navy, border: '1px solid #263b46', padding: 14, color: '#fff' } },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8, flexWrap: 'wrap' } },
          h('div', { style: { minWidth: 0 } },
            h('div', { style: { fontWeight: 650 } }, '红外热像 · 实时采集'),
            h('div', { style: { color: '#91a7b1', fontSize: 10, marginTop: 2 } },
              live ? `${SOURCE_LABEL[live.source] || live.source} · ${live.width || '-'}×${live.height || '-'} · ${live.fps || 0} fps` : 'THERMAL / LIVE UVC STREAM')),
          h('div', { style: { display: 'flex', gap: 6, alignItems: 'center' } },
            Badge({ tone: badge.tone }, badge.text),
            liveOn ? Button('停止', onDisconnect, false, { padding: '4px 9px', fontSize: 11, background: 'rgba(255,255,255,.08)', color: '#d6e2e7', borderColor: '#3a505b' })
              : Button(busy ? '连接中…' : '连接摄像头', onConnect, true, { padding: '4px 10px', fontSize: 11 }))),
        h('div', { style: { position: 'relative', height: 'clamp(340px,43vh,560px)', borderRadius: 11, overflow: 'hidden',
          background: '#0b1620', display: 'grid', placeItems: 'center' } },
          liveOn && live
            ? h('img', {
              key: `live-${stamp}`,
              src: `/wound-clinic/live/stream?ts=${stamp}`,
              alt: '实时热像画面',
              style: { width: '100%', height: '100%', objectFit: 'contain', display: 'block' },
            })
            : h('div', { style: { padding: '0 26px', textAlign: 'center', color: '#9db0b9', fontSize: 12, lineHeight: '19px' } },
              h('div', { style: { fontSize: 13, color: '#dbe6ea', fontWeight: 650, marginBottom: 6 } }, error ? '实时采集未连接' : '未开始实时采集'),
              h('div', null, error || '连接后这里显示海康热像仪的实时画面；温度与 ΔT 只在拿到 16bit 原始温度帧并完成标定后才可用。'),
              h('div', { style: { marginTop: 10, color: '#7c929d', fontSize: 10 } }, '采集在本机完成，画面不离开这台机器'))),
        h('div', { style: { display: 'flex', gap: 14, marginTop: 11, color: '#9db0b9', fontSize: 10, flexWrap: 'wrap', alignItems: 'center' } },
          h('span', null, '● 自动热区 ROI'), h('span', null, '○ 远端参考皮温'),
          temps && h('span', { style: { color: '#e8f1f4' } }, `Tmin ${Number(temps.t_min_c).toFixed(1)}°C · Tmax ${Number(temps.t_max_c).toFixed(1)}°C · ΔT ${Number(temps.delta_t_c) >= 0 ? '+' : ''}${Number(temps.delta_t_c).toFixed(2)}°C`),
          h('span', { style: { marginLeft: 'auto' } },
            Button(busy ? '抓拍中…' : '记录当前帧', onCapture, false, { padding: '4px 9px', fontSize: 11, background: 'rgba(255,255,255,.08)', color: '#d6e2e7', borderColor: '#3a505b' }))),
        liveOn && live && !live.has_temperature && h('div', { style: { marginTop: 8, color: '#f5c99b', fontSize: 10, lineHeight: '16px' } },
          live.source === 'color'
            ? '当前相机只输出伪彩色视频：可以看到画面，但不能反推可靠温度，抓拍结果会被质量门禁阻断。'
            : '已拿到 16bit 原始帧但尚未标定：在下面填入 scale/offset（或用已知温度点两点标定）后才会出现摄氏温度与 ΔT。'),
        live && live.engine && h('div', { style: { marginTop: 8, color: '#a9bdc6', fontSize: 10, lineHeight: '16px' } },
          `${live.engine.weight_label || '分割'} · 置信度 ${Number(live.engine.mask_confidence || 0).toFixed(2)} · ${live.engine.note || ''}`),
        h('div', { style: { marginTop: 9, paddingTop: 9, borderTop: '1px solid #263b46', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 10, color: '#9db0b9' } },
          h('span', null, '设备'),
          h('label', { style: { display: 'inline-flex', gap: 5, alignItems: 'center' } }, '相机',
            h('input', { type: 'number', min: 0, max: 5, value: cfg.camera, onChange: e => onCfgChange('camera', e.target.value),
              'aria-label': '相机索引', style: { width: 46, padding: '3px 5px', borderRadius: 5, border: '1px solid #3a505b',
                background: '#0e2029', color: '#e8f1f4', fontSize: 10 } })),
          onEngine && h('label', { style: { display: 'inline-flex', gap: 5, alignItems: 'center' } }, '分割',
            h('select', { value: (live && live.engine && live.engine.weight) || cfg.weight || 'thermal',
              onChange: e => onEngine('weight', e.target.value), 'aria-label': '分割模型',
              style: { padding: '3px 5px', borderRadius: 5, border: '1px solid #3a505b', background: '#0e2029', color: '#e8f1f4', fontSize: 10 } },
              h('option', { value: 'thermal' }, '热像伪彩分割'),
              h('option', { value: 'u2netp' }, 'U²-Net 小模型'))),
          onEngine && h('label', { style: { display: 'inline-flex', gap: 5, alignItems: 'center' } }, '视图',
            h('select', { value: (live && live.engine && live.engine.view) || cfg.view || 'original',
              onChange: e => onEngine('view', e.target.value), 'aria-label': '热像视图',
              style: { padding: '3px 5px', borderRadius: 5, border: '1px solid #3a505b', background: '#0e2029', color: '#e8f1f4', fontSize: 10 } },
              h('option', { value: 'original' }, '原始热像'),
              h('option', { value: 'compare' }, '去背景对比'),
              h('option', { value: 'removed' }, '去背景'),
              h('option', { value: 'isotherm' }, '等温线'))),
          live && live.source === 'y16' && h(React.Fragment, null,
            h('label', { style: { display: 'inline-flex', gap: 5, alignItems: 'center' } }, 'scale',
              h('input', { type: 'text', value: cfg.scale, placeholder: '如 0.01', onChange: e => onCfgChange('scale', e.target.value),
                'aria-label': 'RAW scale', style: { width: 66, padding: '3px 5px', borderRadius: 5, border: '1px solid #3a505b',
                  background: '#0e2029', color: '#e8f1f4', fontSize: 10 } })),
            h('label', { style: { display: 'inline-flex', gap: 5, alignItems: 'center' } }, 'offset',
              h('input', { type: 'text', value: cfg.offset, placeholder: '如 -273', onChange: e => onCfgChange('offset', e.target.value),
                'aria-label': 'RAW offset', style: { width: 66, padding: '3px 5px', borderRadius: 5, border: '1px solid #3a505b',
                  background: '#0e2029', color: '#e8f1f4', fontSize: 10 } }))),
          Button(busy ? '应用中…' : '应用并重连', onApplyCfg, false, { padding: '3px 9px', fontSize: 10,
            background: 'rgba(255,255,255,.08)', color: '#d6e2e7', borderColor: '#3a505b' })));
    }
    function Thermal({ measurement }) {
      const m = measurement.metrics || {};
      return h('div', { style: { ...S.card, background: C.navy, border: '1px solid #263b46', padding: 14, color: '#fff' } },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 } },
          h('div', null, h('div', { style: { fontWeight: 650 } }, '红外热像 · ROI 分割'),
            h('div', { style: { color: '#91a7b1', fontSize: 10, marginTop: 2 } }, 'THERMAL / PERIWOUND REFERENCE')),
          Badge({ tone: 'orange' }, '示例热像')),
        h('div', { style: { position: 'relative', height: 'clamp(340px,43vh,560px)', borderRadius: 11, overflow: 'hidden',
          background: 'radial-gradient(circle at 49% 49%,#fff4a8 0,#ffc247 5%,#f37935 12%,#b52d55 23%,transparent 38%),radial-gradient(ellipse at 50% 50%,#96315c 0,#48234f 48%,#17263d 82%)' } },
          h('div', { style: { position: 'absolute', inset: 0, opacity: .13,
            backgroundImage: 'linear-gradient(rgba(255,255,255,.25) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.25) 1px,transparent 1px)',
            backgroundSize: '32px 32px' } }),
          h('div', { style: { position: 'absolute', left: '42%', top: '31%', width: '17%', height: '36%', border: '2px solid #fde047',
            borderRadius: '50%', boxShadow: '0 0 0 8px rgba(253,224,71,.08)' } }),
          h('div', { style: { position: 'absolute', left: '43%', top: '26%', color: '#fef9c3', fontSize: 11 } }, 'ROI 01'),
          h('div', { style: { position: 'absolute', left: 14, bottom: 12, padding: '6px 9px', background: 'rgba(9,20,28,.72)',
            borderRadius: 6, color: '#d6e2e7', fontSize: 11 } }, `Tmax ${Number(m.t_wound_max_c || 0).toFixed(2)}°C`),
          h('div', { style: { position: 'absolute', right: 12, top: 14, bottom: 14, width: 9, borderRadius: 4,
            background: 'linear-gradient(to top,#17263d,#48234f,#b52d55,#f37935,#ffc247,#fff4a8)' } }),
          h('div', { style: { position: 'absolute', right: 28, top: 12, color: '#c7d4da', fontSize: 9 } }, '38°C'),
          h('div', { style: { position: 'absolute', right: 28, bottom: 12, color: '#c7d4da', fontSize: 9 } }, '30°C')),
        h('div', { style: { display: 'flex', gap: 16, marginTop: 11, color: '#9db0b9', fontSize: 10, flexWrap: 'wrap' } },
          h('span', null, '● 创口候选区'), h('span', null, '○ 远端健康皮肤参考'),
          h('span', { style: { marginLeft: 'auto' } }, `${measurement.device?.model || '-'} · ${measurement.device?.distance_m || '-'} m`)));
    }
    function preview(measurement) {
      const q = measurement.quality || {};
      const valid = measurement.device?.calibration?.status === 'valid' && q.roi_valid && q.reference_valid && q.temperature_in_range;
      const d = Number(measurement.metrics?.delta_t_c);
      if (!valid || !Number.isFinite(d)) return { level: 'blocked', label: '质量门禁未通过', tone: 'gray' };
      if (d < -0.6) return { level: 'cold', label: '局部低温 · 警惕灌注不足', tone: 'gray' };
      if (d < 0.6) return { level: 'normal', label: '未见明显热异常', tone: 'teal' };
      if (d < 2.2) return { level: 'suspicious', label: '可疑炎症 · 建议复测', tone: 'orange' };
      return { level: 'high', label: '显著热异常 · 感染风险增高', tone: 'orange' };
    }
    function AnalysisPanel({ measurement, onEvidence }) {
      const risk = preview(measurement);
      const m = measurement.metrics || {};
      return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
        h('div', { style: { ...S.card, border: '1px solid #f0d4c4', borderLeft: `4px solid ${C.orange}`,
          background: 'linear-gradient(135deg,#fffaf6,#ffffff)' } },
          h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
            h('div', { style: S.label }, '本地规则预览'), Badge({ tone: risk.tone }, '非确诊')),
          h('div', { style: { fontSize: 16, fontWeight: 750, lineHeight: '24px', margin: '8px 0 6px', color: C.orange } }, risk.label),
          h('div', { style: { color: C.muted, fontSize: 11, lineHeight: '18px' } },
            `ΔT ${Number(m.delta_t_c || 0) >= 0 ? '+' : ''}${Number(m.delta_t_c || 0).toFixed(2)}°C。正式结果须由 wound_thermal_analyze 工具校验，模型不得修改等级。`)),
        h('div', { style: S.card },
          SectionTitle('判定依据', 'EVIDENCE-LINKED INTERPRETATION'),
          h('div', { style: { fontSize: 12, lineHeight: '21px' } }, '创口区与远端参考皮肤存在明显温差；单次红外测温存在假阳性，需在相同条件下复测并结合创面表现。'),
          h('div', { style: { display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' } },
            ['E002', 'E003', 'E004'].map(id => h('button', { key: id, onClick: () => onEvidence(id),
              style: { ...S.button, padding: '3px 8px', color: C.teal } }, id)))),
        h('div', { style: { ...S.card, background: '#f8fafb' } },
          SectionTitle('下一步', 'FOLLOW-UP'),
          h('ol', { style: { margin: 0, paddingLeft: 19, fontSize: 12, lineHeight: '23px' } },
            h('li', null, '同环境、同距离、同参考区复测'),
            h('li', null, '由医护人员结合创面与必要检查评估'),
            h('li', null, '保存为草稿，在报告中心补充详情后再存入患者档案'))),
        h('div', { style: { padding: '0 4px', color: C.muted, fontSize: 10, lineHeight: '17px' } },
          '安全边界：不输出病原学诊断、不推荐抗生素；原始影像默认不离开本机。'));
    }
    function Screen({ measurement, onEvidence, live, liveOn, liveBusy, liveError, liveStamp, liveCfg, onLiveCfg, onLiveApply, onConnect, onDisconnect, onCapture, onLiveEngine }) {
      const m = measurement.metrics || {};
      return h('div', null,
        h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 11, marginBottom: 13 } },
          Metric('创口区均温', Number(m.t_wound_mean_c || 0).toFixed(2), '°C', 'ROI 平均温度'),
          Metric('远端参考皮温', Number(m.t_ref_far_c || 0).toFixed(2), '°C', '健康皮肤参考'),
          Metric('相对温差 ΔT', `${Number(m.delta_t_c || 0) >= 0 ? '+' : ''}${Number(m.delta_t_c || 0).toFixed(2)}`, '°C', '主要筛查指标', C.orange),
          Metric('热区面积占比', (Number(m.area_ratio || 0) * 100).toFixed(1), '%', 'ROI / 全画面')),
        h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(0,1.65fr) minmax(270px,1fr)', gap: 13 } },
          LiveThermal({ live, liveOn, stamp: liveStamp, busy: liveBusy, error: liveError,
            cfg: liveCfg, onCfgChange: onLiveCfg, onApplyCfg: onLiveApply,
            onConnect, onDisconnect, onCapture, onEngine: onLiveEngine }),
          AnalysisPanel({ measurement, onEvidence })));
    }
    function SaveDraftDialog({ measurement, title, busy, onTitle, onCancel, onSave }) {
      const risk = preview(measurement);
      const canSave = Boolean(String(title || '').trim()) && !busy;
      return h('div', { role: 'dialog', 'aria-label': '命名并保存草稿',
        style: { position: 'absolute', inset: 0, zIndex: 20, background: 'rgba(7,18,24,.42)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
        onMouseDown: (event) => { if (event.target === event.currentTarget && !busy) onCancel(); } },
        h('div', { style: { width: 'min(460px,100%)', background: '#fff', borderRadius: 14, padding: 20, boxShadow: '0 24px 60px rgba(7,18,24,.3)' } },
          h('div', { style: { fontSize: 15, fontWeight: 750 } }, '保存为草稿'),
          h('div', { style: { ...S.muted, fontSize: 11, marginTop: 3 } }, '草稿会进入报告中心；在那里补充详情后，再存入患者档案。'),
          h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' } },
            Badge({ tone: risk.tone }, risk.label),
            h('span', { style: { fontSize: 11, color: C.muted } }, `${fmtDelta(measurement.metrics?.delta_t_c)} · ${measurement.measurement_id || '-'}`)),
          h('label', { style: { display: 'block', marginTop: 14, ...S.label } }, '草稿名称'),
          h('input', { value: title, autoFocus: true, 'aria-label': '草稿名称',
            onChange: (event) => onTitle(event.target.value),
            onKeyDown: (event) => { if (event.key === 'Enter' && canSave) onSave(); },
            style: { ...fieldInput, marginTop: 5, font: '13px/18px system-ui,"Microsoft YaHei",sans-serif' } }),
          h('div', { style: { display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 } },
            Button('取消', onCancel, false, { disabled: busy }),
            Button(busy ? '保存中…' : '保存草稿', onSave, true, { disabled: !canSave, opacity: canSave ? 1 : .5 }))));
    }
    function Archive({ patients, activePatient, history, reports, onSelect }) {
      const headStyle = { textAlign: 'left', padding: '10px 8px', borderBottom: `1px solid ${C.line}`, color: C.muted, fontSize: 11 };
      const cellStyle = { padding: '11px 8px', borderBottom: `1px solid ${C.line}` };
      const nameOf = (patient) => patient.display_name || patient.patient_ref;
      return h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(220px,300px) minmax(0,1fr)', gap: 13, alignItems: 'start' } },
        h('div', { style: S.card },
          SectionTitle('患者档案', 'LOCAL ARCHIVE · 自动编号'),
          patients.length === 0 && h('div', { style: { padding: '10px 4px', color: C.muted, fontSize: 12, lineHeight: '20px' } },
            '尚无患者档案。在报告中心打开草稿，点击“保存为患者档案”后会自动编号为患者01。'),
          patients.map(patient => h('button', { key: patient.patient_ref, onClick: () => onSelect(patient.patient_ref),
            style: { width: '100%', display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left', marginBottom: 6, padding: '10px 11px',
              border: `1px solid ${activePatient?.patient_ref === patient.patient_ref ? '#c9e6df' : 'transparent'}`,
              background: activePatient?.patient_ref === patient.patient_ref ? C.tealSoft : 'transparent', borderRadius: 9, cursor: 'pointer' } },
            h('span', { style: { width: 34, height: 34, borderRadius: 10, background: '#fff', border: `1px solid ${C.line}`,
              display: 'grid', placeItems: 'center', color: C.teal, fontWeight: 750, fontSize: 13 } }, String(nameOf(patient)).replace('患者', '') || 'P'),
            h('span', { style: { flex: 1, minWidth: 0 } },
              h('div', { style: { fontWeight: 700, fontSize: 13, color: C.ink } }, nameOf(patient)),
              h('div', { style: { ...S.muted, fontSize: 10.5 } }, `${patient.patient_ref} · ${patient.measurement_count || 0} 次测量`)))),
          h('div', { style: { marginTop: 12, padding: '10px 11px', background: C.tealSoft, border: '1px solid #c8e6df', borderRadius: 9, fontSize: 11, lineHeight: '18px', color: C.ink } },
            '档案为伪匿名本地记录，不含姓名与联系方式；测量只追加、不覆盖。')),
        activePatient ? h('div', { style: { display: 'grid', gap: 13 } },
          h('div', { style: S.card },
            SectionTitle('检测记录', `${nameOf(activePatient)} · MEASUREMENT HISTORY`),
            (history || []).length === 0 ? h('div', { style: { padding: '10px 4px', color: C.muted, fontSize: 12 } }, '暂无测量记录') :
              h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: 12 } },
                h('thead', null, h('tr', null, ['测量编号', '采集时间', 'ΔT', '本地等级', '状态'].map(x => h('th', { key: x, style: headStyle }, x)))),
                h('tbody', null, history.map(item => h('tr', { key: item.measurement_id },
                  h('td', { style: cellStyle }, item.measurement_id),
                  h('td', { style: cellStyle }, fmtTime(item.captured_at)),
                  h('td', { style: { ...cellStyle, fontWeight: 700 } }, fmtDelta(item.metrics?.delta_t_c)),
                  h('td', { style: cellStyle }, item.rule_result?.label || '—'),
                  h('td', { style: cellStyle }, Badge({ tone: item.rule_result?.level === 'normal' ? 'teal' : 'orange' }, '已归档')))))),
          h('div', { style: S.card },
            SectionTitle('报告', 'REPORTS · 仍需医护复核'),
            (reports || []).length === 0 ? h('div', { style: { padding: '10px 4px', color: C.muted, fontSize: 12 } }, '暂无报告草稿') :
              reports.map(r => h('div', { key: r.report_id, style: { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: `1px solid ${C.line}` } },
                h('div', { style: { flex: 1 } }, h('div', { style: { fontWeight: 650 } }, r.report_id),
                  h('div', { style: { ...S.muted, fontSize: 11 } }, `${fmtTime(r.created_at)} · ${r.measurement_id}`)),
                Badge({ tone: r.status === 'reviewed' ? 'teal' : 'orange' }, r.status === 'reviewed' ? '已复核' : '草稿 · 待复核'))),
            h('div', { style: { marginTop: 12, fontSize: 11, color: C.muted } }, '报告由本地规则引擎生成并保留哈希；正式结论须由医护人员复核后出具。'))))
          : h('div', { style: { ...S.card, padding: 28, textAlign: 'center', color: C.muted, fontSize: 12 } }, '选择左侧档案查看检测记录与报告'));
    }
    function Trend({ measurement, history }) {
      const real = (history || []).filter(item => Number.isFinite(Number(item.metrics?.delta_t_c)))
        .map(item => Number(item.metrics.delta_t_c)).reverse();
      const values = real.length >= 2 ? real : [0.42, 0.55, 0.71, 1.04, 1.36, 1.82, Number(measurement.metrics?.delta_t_c || 2.28)];
      const scale = Math.max(2.6, ...values.map(v => Math.abs(v))) * 1.15;
      const points = values.map((v, i) => `${35 + i * (605 / Math.max(values.length - 1, 1))},${205 - v * (165 / scale)}`).join(' ');
      return h('div', { style: S.card }, SectionTitle('随访温差趋势', '仅在测量条件相近且质量通过时比较'),
        h('svg', { viewBox: '0 0 660 240', style: { width: '100%', height: 300, background: '#f8fafb', borderRadius: 10 } },
          [0, 1, 2, 3].map(i => h('line', { key: i, x1: 30, x2: 640, y1: 40 + i * 55, y2: 40 + i * 55, stroke: '#dfe7ea', strokeDasharray: '4 4' })),
          h('line', { x1: 30, x2: 640, y1: 205 - 2.2 * (165 / scale), y2: 205 - 2.2 * (165 / scale), stroke: '#fb923c', strokeWidth: 1.5, strokeDasharray: '7 5' }),
          h('text', { x: 540, y: 200 - 2.2 * (165 / scale), fill: '#c2410c', fontSize: 11 }, '2.2°C 预警参考'),
          h('polyline', { points, fill: 'none', stroke: C.teal, strokeWidth: 3, strokeLinejoin: 'round' }),
          values.map((v, i) => h('circle', { key: i, cx: 35 + i * (605 / Math.max(values.length - 1, 1)), cy: 205 - v * (165 / scale), r: 4, fill: '#fff', stroke: C.teal, strokeWidth: 2 })),
          h('text', { x: 35, y: 230, fill: C.muted, fontSize: 10 }, real.length >= 2 ? '已归档测量序列 · 按采集时间排序' : '演示随访序列 · 非真实患者数据')),
        h('div', { style: { marginTop: 10, color: C.muted, fontSize: 11 } }, '趋势用于复测确认，不将单次热异常解释为确诊感染。'));
    }
    function RuleCard({ draft }) {
      const rule = draft.rule_result;
      if (!rule) {
        return h('div', { style: { ...S.card, border: '1px solid #fed7aa', background: '#fff7ed' } },
          h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } }, h('div', { style: S.label }, '本地规则结果'), Badge({ tone: 'orange' }, '质量门禁未通过')),
          h('div', { style: { fontSize: 14, fontWeight: 750, margin: '8px 0 4px', color: C.orange } }, draft.blocked_message || '采集或标定不满足分析条件'),
          h('div', { style: { color: C.muted, fontSize: 11, lineHeight: '18px' } }, '门禁未通过的草稿不能存入患者档案；请重新标定采集后另存草稿。'));
      }
      const tone = rule.level === 'normal' ? 'teal' : 'orange';
      return h('div', { style: { ...S.card, border: '1px solid #f0d4c4', borderLeft: `4px solid ${C.orange}`, background: 'linear-gradient(135deg,#fffaf6,#ffffff)' } },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          h('div', { style: S.label }, '本地规则结果 · 保存草稿时生成'), Badge({ tone }, '非确诊')),
        h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 12, margin: '8px 0 4px' } },
          h('div', { style: { fontSize: 17, fontWeight: 750, color: C.orange } }, rule.label),
          h('div', { style: { fontSize: 13, fontWeight: 700, color: C.ink } }, `ΔT ${fmtDelta(rule.delta_t_c)}`)),
        h('div', { style: { color: C.muted, fontSize: 11, lineHeight: '18px' } }, `规则 ${rule.threshold_version || 'wound-delta-v1'} · 等级由本地规则引擎独占，侧边对话与模型无权修改。`));
    }
    function DraftList({ drafts, onOpen, onNew }) {
      return h('div', null,
        h('div', { style: S.card },
          SectionTitle('草稿列表', 'DRAFTS · 筛查保存后在此补充详情，再存入患者档案', Button('去实时筛查新建草稿', onNew, true)),
          drafts.length === 0 ? h('div', { style: { padding: 26, textAlign: 'center', color: C.muted, fontSize: 12, lineHeight: '20px' } },
            h('div', { style: { fontWeight: 700, color: C.ink, marginBottom: 4 } }, '报告中心还没有草稿'),
            h('div', null, '在“实时筛查”点击“保存草稿”并命名后，草稿会出现在这里（第 2 位）。')) :
            drafts.map(draft => h('button', { key: draft.draft_id, onClick: () => onOpen(draft.draft_id),
              style: { display: 'flex', alignItems: 'center', gap: 13, width: '100%', textAlign: 'left', padding: '13px 14px', marginBottom: 8,
                background: '#fff', border: `1px solid ${C.line}`, borderRadius: 12, cursor: 'pointer' } },
              h('span', { style: { width: 40, height: 40, borderRadius: 11, flex: '0 0 auto', display: 'grid', placeItems: 'center',
                background: draft.status === 'archived' ? '#edf2f4' : C.tealSoft, color: draft.status === 'archived' ? C.muted : C.teal } }, Icon({ name: 'reports', size: 18 })),
              h('span', { style: { flex: 1, minWidth: 0 } },
                h('div', { style: { fontWeight: 700, fontSize: 13, color: C.ink } }, draft.title || draft.draft_id),
                h('div', { style: { ...S.muted, fontSize: 11, marginTop: 2 } }, `${draft.draft_id} · ${draft.measurement_id || '-'} · 更新于 ${fmtTime(draft.updated_at)}`),
                h('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 7 } },
                  draft.rule_result && Badge({ tone: draft.rule_result.level === 'normal' ? 'teal' : 'orange' }, `${draft.rule_result.label} · ΔT ${fmtDelta(draft.rule_result.delta_t_c)}`),
                  draft.quality_gate && draft.quality_gate !== 'passed' && Badge({ tone: 'orange' }, '质量门禁未通过'),
                  draft.detail_count > 0 && Badge({ tone: 'gray' }, `详情 ${draft.detail_count} 项`),
                  draft.supplement_count > 0 && Badge({ tone: 'gray' }, `补充 ${draft.supplement_count} 条`))),
              Badge({ tone: draft.status === 'archived' ? 'gray' : 'orange' }, draft.status === 'archived' ? `已归档 · ${draft.patient_name || draft.patient_ref || ''}` : '草稿'),
              h('span', { style: { color: C.muted, fontSize: 16 } }, '›')))),
        h('div', { style: { fontSize: 11, color: C.muted } }, '草稿与对话记录保存在本机 SQLite；点击任意草稿可查看、补充详情，并打开侧边对话进行修正。'));
    }
    function DraftDetail({ draft, title, detailForm, busy, onTitle, onTitleCommit, onField, onSaveDetails, onArchive, onBack, onOpenAssistant }) {
      const m = draft.measurement?.metrics || {};
      const archived = draft.status === 'archived';
      return h('div', { style: { display: 'grid', gap: 13 } },
        h('div', { style: { ...S.card, display: 'flex', alignItems: 'center', gap: 12 } },
          Icon({ name: 'reports', size: 20 }),
          h('input', { value: title, 'aria-label': '草稿名称', disabled: archived, onChange: (event) => onTitle(event.target.value), onBlur: onTitleCommit,
            onKeyDown: (event) => { if (event.key === 'Enter') event.target.blur(); },
            style: { flex: 1, minWidth: 0, border: '1px solid transparent', borderRadius: 8, padding: '6px 8px', font: '16px/22px system-ui,"Microsoft YaHei",sans-serif',
              fontWeight: 750, color: C.ink, outline: 'none', background: archived ? 'transparent' : '#fff' } }),
          Badge({ tone: archived ? 'gray' : 'orange' }, archived ? `已归档 · ${draft.patient_name || draft.patient_ref || ''}` : '草稿'),
          Button('返回列表', onBack)),
        h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 11 } },
          Metric('创口区均温', Number(m.t_wound_mean_c || 0).toFixed(2), '°C', 'ROI 平均温度'),
          Metric('远端参考皮温', Number(m.t_ref_far_c || 0).toFixed(2), '°C', '健康皮肤参考'),
          Metric('相对温差 ΔT', `${Number(m.delta_t_c || 0) >= 0 ? '+' : ''}${Number(m.delta_t_c || 0).toFixed(2)}`, '°C', '主要筛查指标', C.orange),
          Metric('热区面积占比', (Number(m.area_ratio || 0) * 100).toFixed(1), '%', 'ROI / 全画面')),
        RuleCard({ draft }),
        h('div', { style: S.card },
          SectionTitle('补充详情', 'DETAILS · 可在下方手动修改，或通过右侧循证对话补充',
            Button(archived ? '已归档（只读）' : '保存修改', onSaveDetails, !archived, { disabled: archived || busy })),
          h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10 } },
            Object.entries(DETAIL_LABELS).map(([key, label]) => h('label', { key, style: { display: 'grid', gap: 4 } },
              h('span', { style: S.label }, label),
              h('input', { value: detailForm?.[key] || '', disabled: archived, placeholder: '未记录', onChange: (event) => onField(key, event.target.value), style: fieldInput }))))),
        h('div', { style: { ...S.card, background: '#f8fafb' } },
          SectionTitle('补充记录', 'SUPPLEMENTS · 来自侧边对话提取或手动保存', Button('打开循证对话', onOpenAssistant)),
          (draft.supplements || []).length === 0 ? h('div', { style: { color: C.muted, fontSize: 12 } }, '暂无补充记录。在右侧对话中描述创口部位、病程、表现等，助手提取后会请你确认写入。') :
            draft.supplements.slice().reverse().map((item, index) => h('div', { key: `${item.at}-${index}`, style: { display: 'flex', gap: 10, padding: '8px 0', borderBottom: `1px solid ${C.line}`, fontSize: 12 } },
              h('span', { style: { ...S.muted, fontSize: 11, flex: '0 0 auto', minWidth: 120 } }, fmtTime(item.at)),
              h('span', { style: { flex: 1, lineHeight: '19px' } }, item.text,
                item.fields?.length > 0 && h('div', { style: { ...S.muted, fontSize: 10.5, marginTop: 2 } }, `已写入：${item.fields.map(k => DETAIL_LABELS[k] || k).join('、')}`)),
              Badge({ tone: 'gray' }, item.source === 'chat' ? '对话提取' : '手动')))),
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
          h('div', { style: { color: C.muted, fontSize: 11, lineHeight: '18px', flex: 1, minWidth: 240 } },
            archived ? `已存入患者档案 ${draft.patient_name || ''}（${draft.patient_ref || ''}）；记录只追加，不覆盖。` : '存入患者档案时自动编号（患者01、患者02…），同时写入测量记录与报告草稿；仅质量门禁通过的草稿可归档。'),
          archived ? Button('查看患者档案', () => onArchive(true), false) : Button('保存为患者档案', () => onArchive(false), true, { disabled: busy || draft.quality_gate !== 'passed' })));
    }
    function Evidence({ focus }) {
      return h('div', { style: { display: 'grid', gap: 11 } }, EVIDENCE.map(e =>
        h('div', { key: e.id, style: { ...S.card, borderLeft: focus === e.id ? `4px solid ${C.teal}` : `4px solid transparent` } },
          h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 7 } }, Badge({}, e.id), Badge({ tone: 'gray' }, `${e.type} · ${e.year}`)),
          h('div', { style: { fontWeight: 700, marginBottom: 7 } }, e.title),
          h('div', { style: { fontSize: 12, lineHeight: '20px' } }, e.text),
          h('div', { style: { fontSize: 11, color: C.muted, margin: '7px 0' } }, `适用边界：${e.scope}`),
          h('a', { href: e.url, target: '_blank', rel: 'noreferrer', style: { color: C.teal, fontSize: 11 } }, '查看原始来源 ↗'))));
    }

    function AssistantMeta({ meta }) {
      if (!meta) return null;
      const rule = meta.rule;
      const tone = !rule ? 'gray' : rule.level === 'normal' ? 'teal' : rule.level === 'blocked' ? 'gray' : 'orange';
      const delta = rule && Number.isFinite(Number(rule.delta_t_c))
        ? `${Number(rule.delta_t_c) >= 0 ? '+' : ''}${Number(rule.delta_t_c).toFixed(2)}°C` : '';
      const violations = Array.isArray(meta.violations) ? meta.violations : [];
      const reason = REASON_LABEL[meta.reason] || meta.reason;
      const detail = meta.reason === 'ACCOUNT_QUOTA'
        ? '充值或切换可用模型后，下次提问会自动恢复 DeepSeek 回答' : meta.detail;
      return h('div', { style: { marginTop: 8, display: 'grid', gap: 6 } },
        h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
          rule && Badge({ tone }, `本地规则：${rule.label}${delta ? ` · ΔT ${delta}` : ''}`),
          meta.modelUsed ? Badge({ tone: 'gray' }, `模型 · ${meta.model || '已配置路由'}`) : Badge({ tone: 'gray' }, '规则模板 · 未使用模型'),
          meta.engine === 'blocked' && Badge({ tone: 'orange' }, '质量门禁未通过'),
          meta.engine === 'unavailable' && Badge({ tone: 'orange' }, '规则引擎不可用')),
        violations.length > 0 && h('div', { style: { padding: '8px 10px', borderRadius: 8, background: '#fff7ed', border: '1px solid #fed7aa', color: '#9a3412', fontSize: 11, lineHeight: '17px' } },
          h('div', { style: { fontWeight: 700, marginBottom: 3 } }, '模型回答未通过安全校验，已改用本地规则模板'),
          violations.map((item, index) => h('div', { key: `${item.code}-${index}` },
            `· ${item.message}${item.snippet ? `：${item.snippet}` : ''}`))),
        !meta.modelUsed && reason && violations.length === 0 && h('div', { style: { fontSize: 10, color: C.muted } },
          `回退原因：${reason}${detail ? `（${detail}）` : ''}`));
    }

    function AssistantPanel(props) {
      const { messages, busy, phase, error, notice, rules, rulesOpen, input, measurement, maximized, authoritativeRule, draft, pendingDetails } = props;
      const listRef = React.useRef(null);
      React.useEffect(() => {
        const node = listRef.current;
        if (node) node.scrollTop = node.scrollHeight;
      }, [messages, busy, phase, error, notice]);
      const m = measurement.metrics || {};
      const quick = rules && Array.isArray(rules.quick_prompts) && rules.quick_prompts.length
        ? rules.quick_prompts : QUICK_FALLBACK;
      const canSend = !busy && Boolean(String(input || '').trim());
      const disclaimer = (rules && rules.disclaimer) || '辅助筛查，不替代临床诊断；回答不写入正式档案。';
      const deltaText = `ΔT ${Number(m.delta_t_c || 0) >= 0 ? '+' : ''}${Number(m.delta_t_c || 0).toFixed(2)}°C`;
      const ruleBadge = authoritativeRule
        ? Badge({ tone: authoritativeRule.level === 'normal' ? 'teal' : authoritativeRule.level === 'blocked' ? 'gray' : 'orange' },
          `本地规则：${authoritativeRule.label}`)
        : Badge({ tone: 'gray' }, '待本地规则校验');

      const bubble = (message) => {
        const isUser = message.role === 'user';
        return h('div', { key: message.id, style: { display: 'flex', flexDirection: 'column', alignItems: isUser ? 'flex-end' : 'stretch', gap: 4 } },
          h('div', { style: { fontSize: 9, color: C.muted, letterSpacing: '.07em' } }, isUser ? '你' : '医师助手'),
          h('div', { style: { maxWidth: '100%', boxSizing: 'border-box', padding: '9px 11px', borderRadius: isUser ? '11px 11px 3px 11px' : '11px 11px 11px 3px',
            background: isUser ? C.tealSoft : '#fff', border: `1px solid ${isUser ? '#cbe7e0' : C.line}`,
            boxShadow: '0 1px 2px rgba(21,46,56,.03)', fontSize: 12, lineHeight: '20px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' } },
          message.text),
          !isUser && AssistantMeta({ meta: message.meta }));
      };

      const ruleSection = (section) => h('div', { key: section.id },
        h('div', { style: { fontWeight: 700, fontSize: 11, marginBottom: 4, color: C.teal } }, section.title),
        h('ul', { style: { margin: 0, paddingLeft: 16, fontSize: 11, lineHeight: '18px', color: '#33474f' } },
          (section.items || []).map((item, index) => h('li', { key: index, style: { marginBottom: 2 } }, item))));

      const chatView = h('div', { style: { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 } },
        h('div', { ref: listRef, role: 'log', 'aria-live': 'polite',
          style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 13px', display: 'grid', gap: 10, alignContent: 'start' } },
          messages.length === 0 && h('div', { style: { padding: '12px 4px', color: C.muted, fontSize: 12, lineHeight: '20px' } },
            draft ? h(React.Fragment, null,
              h('div', { style: { fontWeight: 700, color: C.ink, fontSize: 13, marginBottom: 5 } }, draft.status === 'archived' ? '这份草稿已归档，可继续提问解释' : '围绕这份草稿补充或修正详情'),
              h('div', null, draft.status === 'archived' ? '草稿内容只读；仍可询问 ΔT 解读、复测间隔、证据与局限。' : '例如：“创口在左小腿外侧，两周了，有少量渗液，正在用碘伏换药。”助手会把部位、病程、表现提取出来，经你确认后写入草稿。'))
              : h(React.Fragment, null,
                h('div', { style: { fontWeight: 700, color: C.ink, fontSize: 13, marginBottom: 5 } }, '询问本次测量的解释'),
                h('div', null, '例如：这个 ΔT 说明什么？需要复测吗？这些结论有哪些证据和限制？')),
            h('div', { style: { marginTop: 9, padding: '9px 10px', borderRadius: 9, background: C.tealSoft, border: '1px solid #cbe7e0', color: '#0f766e', fontSize: 11, lineHeight: '17px' } },
              '本窗口只解释本地规则结果：不确诊、不排除感染、不推荐用药；风险等级由规则引擎独占，模型无权修改。')),
          messages.map(bubble),
          busy && h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: C.muted, padding: '4px 2px' } },
            h('span', { style: { width: 7, height: 7, borderRadius: '50%', background: C.teal, boxShadow: `0 0 0 3px ${C.tealSoft}` } }),
            phase || '正在按医师角色规则生成…')),

        error && h('div', { role: 'alert', style: { margin: '0 13px 8px', padding: '8px 10px', borderRadius: 8, background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', fontSize: 11, lineHeight: '17px', display: 'flex', gap: 8, alignItems: 'flex-start' } },
          h('span', { style: { flex: 1 } }, error),
          h('button', { onClick: props.onDismissError, title: '关闭提示', 'aria-label': '关闭错误提示',
            style: { border: 'none', background: 'transparent', color: '#991b1b', cursor: 'pointer', fontSize: 15, lineHeight: 1, padding: 0 } }, '×')),

        notice && h('div', { style: { margin: '0 13px 8px', padding: '7px 10px', borderRadius: 8, background: '#f4f7f8', border: `1px solid ${C.line}`, color: C.muted, fontSize: 11, lineHeight: '17px', display: 'flex', gap: 8, alignItems: 'center' } },
          h('span', { style: { flex: 1 } }, notice),
          props.onRetry && h('button', { onClick: props.onRetry, style: { ...S.button, padding: '3px 8px', fontSize: 10.5 } }, '重试上次问题')),

        pendingDetails && Object.keys(pendingDetails.fields || {}).length > 0 && h('div', { role: 'status', style: { margin: '0 13px 8px', padding: '9px 10px', borderRadius: 9, background: '#fff7ed', border: '1px solid #fed7aa', fontSize: 11, lineHeight: '18px', color: '#7c2d12' } },
          h('div', { style: { fontWeight: 700, marginBottom: 3 } }, '从刚才的对话提取到补充信息，是否写入草稿？'),
          Object.entries(pendingDetails.fields).map(([key, value]) => h('div', { key }, `${DETAIL_LABELS[key] || key}：${value}`)),
          h('div', { style: { display: 'flex', gap: 6, marginTop: 7 } },
            Button('写入草稿', props.onApplyPending, true, { padding: '4px 9px', fontSize: 11 }),
            Button('忽略', props.onDismissPending, false, { padding: '4px 9px', fontSize: 11 }))),

        h('div', { style: { padding: '8px 13px 0', display: 'flex', flexWrap: 'wrap', gap: 6 } },
          quick.map((text, index) => h('button', { key: index, onClick: () => props.onQuick(text), disabled: busy,
            style: { ...S.button, padding: '4px 8px', fontSize: 10.5, fontWeight: 500, color: '#3f5760', opacity: busy ? .55 : 1 } }, text))),

        h('div', { style: { padding: '8px 12px 10px', borderTop: `1px solid ${C.line}`, background: '#fff', marginTop: 8 } },
          h('textarea', {
            value: input,
            onChange: event => props.onInput(event.target.value),
            onKeyDown: event => {
              if ((event.nativeEvent && event.nativeEvent.isComposing) || event.isComposing || event.keyCode === 229) return;
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (canSend) props.onSend(input); }
            },
            onFocus: event => { event.target.style.borderColor = C.teal; event.target.style.boxShadow = '0 0 0 3px rgba(15,118,110,.12)'; },
            onBlur: event => { event.target.style.borderColor = C.line; event.target.style.boxShadow = 'none'; },
            rows: 2,
            autoFocus: !rulesOpen,
            placeholder: draft && draft.status !== 'archived' ? '补充或修正草稿详情，例如“创口在左小腿，两周，有渗液”；也可以提问' : '向医师助手提问：例如“这个 ΔT 说明什么？”',
            'aria-label': '向医师助手提问',
            style: { width: '100%', boxSizing: 'border-box', resize: 'none', border: `1px solid ${C.line}`, borderRadius: 9,
              padding: '8px 10px', font: '12px/19px system-ui,"Microsoft YaHei",sans-serif', color: C.ink, outline: 'none', background: '#fff', boxShadow: 'none' },
          }),
          h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 7 } },
            h('span', { style: { flex: 1, fontSize: 9.5, color: C.muted, lineHeight: '14px' } }, 'Enter 发送 · Shift+Enter 换行'),
            busy && h('button', { onClick: props.onStop, style: { ...S.button, padding: '6px 9px' } }, '停止'),
            h('button', {
              onClick: () => { if (canSend) props.onSend(input); },
              disabled: !canSend,
              'aria-label': busy ? '正在生成回答' : '发送问题',
              style: { ...S.primary, padding: '7px 12px', display: 'inline-flex', alignItems: 'center', gap: 5,
                opacity: canSend ? 1 : .5, cursor: canSend ? 'pointer' : 'default' },
            }, Icon({ name: 'send', size: 13 }), busy ? '生成中' : '发送')),
          h('div', { style: { fontSize: 9.5, color: C.muted, lineHeight: '14px', marginTop: 5 } },
            `${disclaimer} · 仅发送测量编号与去标识化指标，不发送影像与身份信息`)));

      const rulesView = h('div', { id: 'wound-clinic-assistant-rules', role: 'dialog', 'aria-label': '医师角色规则',
        style: { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 } },
        h('div', { style: { flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, padding: '10px 13px', borderBottom: `1px solid ${C.line}`, background: '#fff' } },
          h('div', { style: { flex: 1 } },
            h('div', { style: { fontWeight: 700, fontSize: 12 } }, '医师角色规则'),
            h('div', { style: { fontSize: 10, color: C.muted } }, rules ? `${rules.version} · ${rules.updated_at || ''}` : '加载中…')),
          h('button', { onClick: props.onToggleRules, style: { ...S.button, padding: '5px 9px' } }, '返回对话')),
        h('div', { style: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 13px', display: 'grid', gap: 12, alignContent: 'start' } },
          !rules && h('div', { style: { fontSize: 12, color: C.muted } }, '规则加载失败，请稍后重试。'),
          rules && h(React.Fragment, null,
            h('div', { style: { padding: '10px 11px', background: C.tealSoft, border: '1px solid #cbe7e0', borderRadius: 10, fontSize: 11, lineHeight: '18px', color: C.ink } },
              h('div', { style: { fontWeight: 700, marginBottom: 3 } }, rules.role),
              rules.identity,
              h('div', { style: { marginTop: 5, color: C.muted } }, `适用范围：${rules.scope}`)),
            (rules.sections || []).map(ruleSection),
            (rules.enforcement || []).length > 0 && h('div', { style: { padding: '9px 11px', background: '#f7fafb', border: `1px solid ${C.line}`, borderRadius: 9, fontSize: 11, lineHeight: '18px', color: C.muted } },
              h('div', { style: { fontWeight: 700, color: C.ink, marginBottom: 3 } }, '如何执行'),
              rules.enforcement.map((item, index) => h('div', { key: index }, `· ${item}`))),
            h('div', { style: { fontSize: 10, color: C.muted, lineHeight: '16px' } }, rules.disclaimer))));

      const panelStyle = props.narrow
        ? { position: 'absolute', right: 0, top: 0, bottom: 0, zIndex: 6, width: 'min(380px, 92%)', maxWidth: '100%',
          flex: '0 0 auto', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fbfdfd',
          borderLeft: `1px solid ${C.line}`, boxShadow: '-14px 0 34px rgba(7,18,24,.18)' }
        : { position: 'relative', zIndex: 5, width: maximized ? 'clamp(320px, 26vw, 440px)' : 'clamp(320px, 30vw, 400px)',
          flex: '0 0 auto', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fbfdfd',
          borderLeft: `1px solid ${C.line}`, boxShadow: '-5px 0 18px rgba(21,46,56,.035)' };

      return h('aside', {
        id: 'wound-clinic-assistant',
        'aria-label': '循证对话侧边窗口',
        style: panelStyle,
      },
        h('div', { style: { padding: '11px 13px', borderBottom: `1px solid ${C.line}`, background: '#fff', display: 'flex', alignItems: 'center', gap: 9 } },
          h('span', { style: { width: 30, height: 30, borderRadius: 9, background: C.tealSoft, color: C.teal, display: 'grid', placeItems: 'center', flex: '0 0 auto' } },
            Icon({ name: 'assistant', size: 16 })),
          h('div', { style: { flex: 1, minWidth: 0 } },
            h('div', { style: { fontWeight: 750, fontSize: 13 } }, '循证对话'),
            h('div', { style: { fontSize: 10, color: C.muted } }, draft ? (draft.status === 'archived' ? '草稿已归档 · 只读解释' : '草稿模式 · 可补充详情') : '医师角色 · 只解释不确诊')),
          h('button', { onClick: props.onToggleRules, style: { ...S.button, padding: '5px 9px', fontSize: 11 },
            title: '查看医师角色规则', 'aria-expanded': rulesOpen, 'aria-controls': 'wound-clinic-assistant-rules' }, rulesOpen ? '返回' : '规则'),
          h('button', { onClick: props.onClose, style: { ...S.button, padding: '5px 7px', display: 'inline-flex', alignItems: 'center' },
            title: '收起到右侧', 'aria-label': '收起循证对话' }, Icon({ name: 'panelClose', size: 14 }))),

        h('div', { style: { padding: '8px 13px', borderBottom: `1px solid ${C.line}`, background: '#f5faf9', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', fontSize: 10, color: C.muted } },
          h('span', { style: { fontWeight: 650, color: C.ink } }, '上下文'),
          draft && Badge({ tone: draft.status === 'archived' ? 'gray' : 'orange' }, `草稿：${draft.title || draft.draft_id}`),
          ruleBadge,
          h('span', null, deltaText),
          h('span', { title: '测量编号会随去标识化指标发送给模型' }, measurement.measurement_id || '-'),
          h('span', { style: { marginLeft: 'auto' }, title: '档案号仅本地显示，不发送给模型' }, measurement.patient_ref || '')),

        rulesOpen ? rulesView : chatView);
    }

    const QUICK_FALLBACK = ['这组数值怎么解读', '需要复测吗？间隔多久', '证据和局限是什么', '哪些情况需要尽快就医', '这份结果能写进报告吗'];
    const REASON_LABEL = {
      rule_violation: '安全校验未通过', empty_output: '模型没有返回内容', aborted: '已中止',
      no_model_configured: '未配置模型路由', llm_unavailable: '模型服务不可用',
      stream_failed: '模型请求失败', timeout: '请求超时', quality_gate_blocked: '质量门禁未通过',
      NO_ADAPTER: '模型适配器未注册', MISSING_CREDENTIAL: '缺少模型凭据', AUTH: '模型鉴权失败',
      RATE_LIMIT: '模型限流', QUOTA: '模型额度不足', ACCOUNT_QUOTA: '模型账户余额不足', CONTEXT_WINDOW_EXCEEDED: '上下文超限',
    };

    function Workstation(props) {
      const native = Boolean(props && props.native);
      const embedded = Boolean(props && props.embedded) && !native;
      const sessionId = props && props.sessionId;
      const [open, setOpen] = React.useState(false);
      const [tab, setTab] = React.useState('screen');
      const [measurement, setMeasurement] = React.useState(DEMO);
      const [notice, setNotice] = React.useState('');
      const [drafts, setDrafts] = React.useState([]);
      const [focusEvidence, setFocusEvidence] = React.useState('');
      const [maximized, setMaximized] = React.useState(false);
      const [assistantOpen, setAssistantOpen] = React.useState(false);
      const [assistantMessages, setAssistantMessages] = React.useState([]);
      const [assistantBusy, setAssistantBusy] = React.useState(false);
      const [assistantPhase, setAssistantPhase] = React.useState('');
      const [assistantRules, setAssistantRules] = React.useState(null);
      const [rulesOpen, setRulesOpen] = React.useState(false);
      const [assistantInput, setAssistantInput] = React.useState('');
      const [assistantError, setAssistantError] = React.useState('');
      const [assistantNotice, setAssistantNotice] = React.useState('');
      const [viewportWidth, setViewportWidth] = React.useState(() => (typeof window !== 'undefined' && window.innerWidth) || 1440);
      // 草稿工作流：报告中心列表/详情、命名对话框、详情提取确认、患者档案。
      const [draftView, setDraftView] = React.useState('list');
      const [activeDraft, setActiveDraft] = React.useState(null);
      const [saveDialog, setSaveDialog] = React.useState(false);
      const [draftTitle, setDraftTitle] = React.useState('');
      const [pendingDetails, setPendingDetails] = React.useState(null);
      const [patients, setPatients] = React.useState([]);
      const [activePatient, setActivePatient] = React.useState(null);
      const [patientHistory, setPatientHistory] = React.useState([]);
      const [patientReports, setPatientReports] = React.useState([]);
      const [workflowBusy, setWorkflowBusy] = React.useState(false);
      const [detailForm, setDetailForm] = React.useState({});
      // 实时筛查：摄像头采集状态、连接、抓拍。
      const [live, setLive] = React.useState(null);
      const [liveOn, setLiveOn] = React.useState(false);
      const [liveBusy, setLiveBusy] = React.useState(false);
      const [liveError, setLiveError] = React.useState('');
      const [liveStamp, setLiveStamp] = React.useState(() => Date.now());
      const [liveCfg, setLiveCfg] = React.useState({ camera: 0, scale: '', offset: '', weight: 'thermal', view: 'original' });
      const fileRef = React.useRef(null);
      const abortRef = React.useRef(null);
      const liveTriedRef = React.useRef(false);
      const assistantRequestRef = React.useRef(false);
      const lastQuestionRef = React.useRef('');
      const draftsLoadedRef = React.useRef(false);
      const patientsLoadedRef = React.useRef(false);
      const tabs = TABS;
      React.useEffect(() => {
        if (tab === 'reports' && !draftsLoadedRef.current) void loadDrafts();
        if (tab === 'archive' && !patientsLoadedRef.current) void loadPatients();
        if (tab === 'screen' && !liveOn && !liveBusy && !liveTriedRef.current) {
          liveTriedRef.current = true;
          void connectLive(true);
        }
      }, [tab, liveOn, liveBusy]);
      React.useEffect(() => {
        if (!liveOn) return undefined;
        const timer = window.setInterval(() => { void refreshLiveStatus(); }, 1500);
        return () => window.clearInterval(timer);
      }, [liveOn]);
      React.useEffect(() => {
        const onKey = (event) => {
          if (event.key !== 'Escape' || (!open && !native)) return;
          if (saveDialog) { setSaveDialog(false); return; }
          if (rulesOpen) { setRulesOpen(false); return; }
          if (assistantOpen) { setAssistantOpen(false); return; }
          if (native) return;
          if (maximized) setMaximized(false); else setOpen(false);
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
      }, [open, maximized, rulesOpen, assistantOpen, native, saveDialog]);
      React.useEffect(() => {
        const onResize = () => setViewportWidth(window.innerWidth || 0);
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
      }, []);
      const narrow = viewportWidth > 0 && viewportWidth < 1180;
      const flash = (text) => { setNotice(text); window.setTimeout(() => setNotice(''), 3200); };
      const importFile = async (event) => {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        try {
          const parsed = JSON.parse(await file.text());
          if (!parsed.metrics || !parsed.quality || !parsed.device) throw new Error('缺少 metrics / quality / device');
          setMeasurement(parsed); setTab('screen'); setActiveDraft(null); setDraftView('list'); setPendingDetails(null);
          setAssistantMessages([]); setAssistantError(''); setAssistantNotice('');
          flash('测量 JSON 已载入。核对后点击“保存草稿”命名，草稿会进入报告中心。');
        } catch (error) { flash(`导入失败：${error.message}`); }
        event.target.value = '';
      };
      // ---- 草稿工作流：全部经本机回环路由落到 SQLite，不经过模型 ----
      const api = async (path, body) => {
        const response = await fetch(path, body === undefined
          ? { headers: { accept: 'application/json' } }
          : { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body) });
        const text = await response.text();
        let data = null;
        try { data = JSON.parse(text); } catch { data = null; }
        if (!response.ok) throw new Error(httpHint(response.status, text));
        if (!data || data.ok === false) {
          const err = (data && data.error) || {};
          throw new Error(err.message || '本地服务返回失败');
        }
        return data;
      };
      // ---- 实时采集：状态、连接、抓拍（相机由本机常驻 Python 服务独占）----
      const refreshLiveStatus = async () => {
        try {
          const data = await api('/wound-clinic/live/status');
          setLive(data);
          setLiveError(String(data.error || ''));
          setLiveOn(true);
          return data;
        } catch (error) {
          setLive(null);
          setLiveOn(false);
          setLiveError(error.message);
          return null;
        }
      };
      const connectLive = async (silent) => {
        if (liveBusy) return null;
        setLiveBusy(true);
        try {
          const data = await refreshLiveStatus();
          if (data) {
            setLiveStamp(Date.now());
            if (!silent) flash(`实时采集已连接：${SOURCE_LABEL[data.source] || data.source}，${data.width || '-'}×${data.height || '-'}。`);
          } else if (!silent) {
            flash('实时采集连不上：确认摄像头已接入；若提示缺少依赖，先在终端 pip install opencv-python numpy。');
          }
          return data;
        } finally { setLiveBusy(false); }
      };
      const disconnectLive = async () => {
        setLiveOn(false);
        setLive(null);
        try {
          await api('/wound-clinic/live/stop', {});
          flash('已停止实时采集，相机已释放。');
        } catch (error) { flash(`停止实时采集失败：${error.message}`); }
      };
      const applyLiveConfig = async () => {
        if (liveBusy) return;
        setLiveBusy(true);
        try {
          const patch = { camera: Number(liveCfg.camera) || 0 };
          const scale = String(liveCfg.scale || '').trim();
          const offset = String(liveCfg.offset || '').trim();
          if (scale !== '') patch.scale = Number(scale);
          if (offset !== '') patch.offset = Number(offset);
          const data = await api('/wound-clinic/live/config', patch);
          setLive(data.status || null);
          setLiveError(String((data.status && data.status.error) || ''));
          setLiveOn(Boolean(data.status));
          setLiveStamp(Date.now());
          flash(`已按相机 ${patch.camera} 重启采集：${SOURCE_LABEL[(data.status || {}).source] || '已连接'}。`);
        } catch (error) { flash(`切换采集配置失败：${error.message}`); }
        finally { setLiveBusy(false); }
      };

      const changeLiveEngine = async (key, value) => {
        setLiveCfg(cfg => ({ ...cfg, [key]: value }));
        try {
          const data = await api('/wound-clinic/live/engine', { [key]: value });
          setLive(data.status || null);
          setLiveStamp(Date.now());
          flash(key === 'weight'
            ? `已切换分割模型：${value === 'u2netp' ? 'U²-Net 小模型' : '热像伪彩分割'}。`
            : `已切换视图：${value}。`);
        } catch (error) { flash(`实时引擎设置失败：${error.message}`); }
      };

      const captureLive = async () => {
        if (liveBusy) return;
        setLiveBusy(true);
        try {
          const data = await api('/wound-clinic/live/measurement');
          const captured = data.measurement;
          setMeasurement(captured);
          setActiveDraft(null); setDraftView('list'); setPendingDetails(null);
          setAssistantMessages([]); setAssistantError(''); setAssistantNotice('');
          setTab('screen');
          const usable = captured.device?.calibration?.status === 'valid'
            && captured.quality?.roi_valid && captured.quality?.reference_valid && captured.quality?.temperature_in_range;
          const warn = (captured.quality?.warnings || [])[0];
          flash(usable
            ? `已记录当前帧：ΔT ${fmtDelta(captured.metrics?.delta_t_c)}，可继续保存草稿。`
            : `已记录当前帧，但质量门禁未通过${warn ? `（${warn}）` : ''}，只能存草稿、不能归档。`);
        } catch (error) { flash(`抓拍失败：${error.message}`); }
        finally { setLiveBusy(false); }
      };

      const loadDrafts = async () => {        try {
          const data = await api('/wound-clinic/draft/list');
          setDrafts(Array.isArray(data.drafts) ? data.drafts : []);
          draftsLoadedRef.current = true;
        } catch (error) { flash(`草稿列表读取失败：${error.message}`); }
      };
      const loadPatients = async () => {
        try {
          const data = await api('/wound-clinic/archive/list');
          const list = Array.isArray(data.patients) ? data.patients : [];
          setPatients(list); patientsLoadedRef.current = true;
          return list;
        } catch (error) { flash(`患者档案读取失败：${error.message}`); return []; }
      };
      const selectPatient = async (patientRef, list) => {
        const pool = list || patients;
        setActivePatient(pool.find(item => item.patient_ref === patientRef) || { patient_ref: patientRef });
        setPatientHistory([]); setPatientReports([]);
        try {
          const [history, reports] = await Promise.all([
            api(`/wound-clinic/archive/history?patient_ref=${encodeURIComponent(patientRef)}`),
            api(`/wound-clinic/report/list?patient_ref=${encodeURIComponent(patientRef)}`),
          ]);
          setPatientHistory(Array.isArray(history.measurements) ? history.measurements : []);
          setPatientReports(Array.isArray(reports.reports) ? reports.reports : []);
        } catch (error) { flash(`档案记录读取失败：${error.message}`); }
      };
      const openSaveDialog = () => {
        setDraftTitle(`创口筛查 ${new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`);
        setSaveDialog(true);
      };
      const applyDraft = (draft) => {
        setActiveDraft(draft); setDraftView('detail'); setDetailForm({ ...(draft.details || {}) });
        setDraftTitle(draft.title || '');
      };
      const saveDraft = async () => {
        const title = String(draftTitle || '').trim();
        if (!title || workflowBusy) return;
        setWorkflowBusy(true);
        try {
          const data = await api('/wound-clinic/draft/create', { title, measurement });
          setSaveDialog(false);
          applyDraft(data.draft);
          setAssistantMessages([]); setAssistantError(''); setAssistantNotice(''); setPendingDetails(null);
          setAssistantOpen(true);
          draftsLoadedRef.current = false;
          setTab('reports');
          flash('草稿已保存到报告中心。可在右侧循证对话补充详情，确认后再存入患者档案。');
        } catch (error) { flash(`保存草稿失败：${error.message}`); }
        finally { setWorkflowBusy(false); }
      };
      const openDraft = async (draftId) => {
        try {
          const data = await api(`/wound-clinic/draft/get?draft_id=${encodeURIComponent(draftId)}`);
          applyDraft(data.draft);
          setAssistantMessages(Array.isArray(data.draft.chat) ? data.draft.chat.map((item, index) => ({ id: `h-${index}`, role: item.role, text: item.text })) : []);
          setAssistantError(''); setAssistantNotice(''); setPendingDetails(null);
          setAssistantOpen(true);
        } catch (error) { flash(`打开草稿失败：${error.message}`); }
      };
      const updateDraft = async (patch) => {
        if (!activeDraft || activeDraft.status !== 'draft') return null;
        const data = await api('/wound-clinic/draft/update', { draft_id: activeDraft.draft_id, ...patch });
        applyDraft(data.draft);
        draftsLoadedRef.current = false;
        void loadDrafts();
        return data.draft;
      };
      const commitTitle = async () => {
        const title = String(draftTitle || '').trim();
        if (!activeDraft || !title || title === activeDraft.title) return;
        try { await updateDraft({ title }); flash('草稿名称已更新。'); }
        catch (error) { flash(`重命名失败：${error.message}`); }
      };
      const saveDetails = async () => {
        try { await updateDraft({ details: detailForm, supplements: [] }); flash('补充详情已保存。'); }
        catch (error) { flash(`保存详情失败：${error.message}`); }
      };
      const applyPending = async () => {
        if (!pendingDetails || !activeDraft) return;
        const merged = { ...(activeDraft.details || {}), ...pendingDetails.fields };
        const snapshot = pendingDetails;
        setPendingDetails(null);
        setDetailForm(merged);
        try {
          await updateDraft({ details: merged, supplements: [{ text: snapshot.question, source: 'chat', fields: Object.keys(snapshot.fields) }] });
          flash('对话中提取的补充信息已写入草稿。');
        } catch (error) { flash(`写入草稿失败：${error.message}`); }
      };
      const archiveDraft = async (viewOnly) => {
        if (viewOnly) { setTab('archive'); if (activeDraft?.patient_ref) { const list = await loadPatients(); void selectPatient(activeDraft.patient_ref, list); } return; }
        if (!activeDraft || workflowBusy) return;
        setWorkflowBusy(true);
        try {
          const data = await api('/wound-clinic/draft/archive', { draft_id: activeDraft.draft_id });
          applyDraft(data.draft);
          draftsLoadedRef.current = false;
          void loadDrafts();
          const list = await loadPatients();
          setActivePatient(list.find(item => item.patient_ref === data.patient_ref) || { patient_ref: data.patient_ref, display_name: data.display_name });
          setTab('archive');
          void selectPatient(data.patient_ref, list);
          flash(`已存入患者档案：${data.display_name}（${data.patient_ref}），测量与报告草稿已写入本地记录。`);
        } catch (error) { flash(`存入患者档案失败：${error.message}`); }
        finally { setWorkflowBusy(false); }
      };
      const showEvidence = (id) => { setFocusEvidence(id); setTab('evidence'); };

      const ensureRules = async () => {
        if (assistantRules) return assistantRules;
        try {
          const response = await fetch('/wound-clinic/assistant/rules', { headers: { accept: 'application/json' } });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          if (data && data.ok && data.rules) { setAssistantRules(data.rules); return data.rules; }
          throw new Error('规则响应为空');
        } catch (error) {
          const hint = error.message === 'HTTP 404'
            ? '侧边对话未启用（插件未加载或 Web GUI 不在本机回环地址）'
            : error.message;
          setAssistantError(`医师角色规则读取失败：${hint}`);
          return null;
        }
      };
      const toggleAssistant = () => {
        setAssistantOpen(current => {
          if (!current) void ensureRules();
          return !current;
        });
      };
      const toggleRules = () => {
        setRulesOpen(current => {
          if (!current) void ensureRules();
          return !current;
        });
      };
      const stopAssistant = () => {
        if (abortRef.current) abortRef.current.abort();
      };
      const httpHint = (status, detail) => {
        const map = {
          400: '问题为空或格式不正确',
          403: '请求来源被拒绝，请从本机 GUI 页面打开工作站',
          404: '插件服务端未加载这些路由：请完全退出并重开 DSH（只刷新页面不够）',
          405: '插件服务端仍是旧版本：请在插件页把本插件禁用再启用，或完全重开 DSH',
          413: '问题或测量数据过大',
        };
        return `${map[status] || `服务返回 ${status}`}${detail ? `（${detail.slice(0, 80)}）` : ''}`;
      };
      const askAssistant = async (question) => {
        const text = String(question || '').trim();
        if (!text || assistantBusy || assistantRequestRef.current) return;
        // 同步锁先于 React 状态更新：快速连点发送/快捷问题不会重复提交同一请求。
        assistantRequestRef.current = true;
        lastQuestionRef.current = text;
        const history = assistantMessages.slice(-8).map(item => ({ role: item.role, text: item.text }));
        setAssistantMessages(list => [...list, { id: `u-${Date.now()}`, role: 'user', text }].slice(-40));
        setAssistantInput('');
        setAssistantError('');
        setAssistantNotice('');
        setAssistantBusy(true);
        setAssistantPhase('正在提交…');
        const controller = new AbortController();
        abortRef.current = controller;
        // 草稿模式：仅在报告中心打开了具体草稿时生效；测量与详情都来自草稿本身。
        const draftContext = activeDraft && tab === 'reports' && draftView === 'detail' ? activeDraft : null;
        const contextMeasurement = draftContext ? draftContext.measurement : measurement;
        let settled = false;
        try {
          const response = await fetch('/wound-clinic/assistant/chat', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              question: text, history, measurement: contextMeasurement,
              draft: draftContext ? {
                draft_id: draftContext.draft_id, title: draftContext.title, status: draftContext.status,
                details: draftContext.details, supplements: (draftContext.supplements || []).slice(-6),
              } : undefined,
            }),
            signal: controller.signal,
          });
          if (!response.ok) {
            let detail = '';
            try { detail = (await response.text()).trim(); } catch { detail = ''; }
            throw new Error(httpHint(response.status, detail));
          }
          if (!response.body) throw new Error('当前浏览器不支持流式响应');
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            let boundary = buffer.indexOf('\n\n');
            while (boundary !== -1) {
              const frame = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              for (const line of frame.split('\n')) {
                if (!line.startsWith('data:')) continue;
                let payload;
                try { payload = JSON.parse(line.slice(5).trim()); } catch { continue; }
                if (payload.type === 'phase') setAssistantPhase(payload.text || '处理中…');
                else if (payload.type === 'final') {
                  settled = true;
                  const answer = { id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
                    role: 'assistant', text: payload.answer || '', meta: payload.meta || null };
                  setAssistantMessages(list => [...list, answer].slice(-40));
                  // 模型从对话中提取到的详情不直接落库：先展示，由用户确认后写入草稿。
                  const extracted = payload.meta && payload.meta.detail_updates;
                  if (draftContext && draftContext.status === 'draft' && extracted && Object.keys(extracted).length > 0) {
                    setPendingDetails({ fields: extracted, question: text });
                  }
                  // 对话记录随草稿保存在本机，重新打开草稿时可回看。
                  if (draftContext && draftContext.status === 'draft') {
                    const chat = [...history, { role: 'user', text }, { role: 'assistant', text: answer.text }]
                      .map(item => ({ role: item.role, text: String(item.text || '').slice(0, 2000) }));
                    void api('/wound-clinic/draft/update', { draft_id: draftContext.draft_id, chat }).catch(() => {});
                  }
                  setAssistantBusy(false);
                  setAssistantPhase('');
                } else if (payload.type === 'error') {
                  settled = true;
                  setAssistantError(`${payload.message || '生成失败'}${payload.hint ? `（${payload.hint}）` : ''}`);
                  setAssistantBusy(false);
                  setAssistantPhase('');
                }
              }
              boundary = buffer.indexOf('\n\n');
            }
          }
          if (!settled && !controller.signal.aborted) {
            setAssistantError('服务没有返回结果（可能超时或连接中断），请重试。');
          }
        } catch (error) {
          if (settled) {
            // 已经收到最终结果，收尾阶段的网络错误不再打扰用户。
          } else if (error.name === 'AbortError') {
            setAssistantNotice('已停止本次生成，可重新提问，或重试上次问题。');
          } else {
            setAssistantError(`对话失败：${error.message || error}`);
          }
        } finally {
          assistantRequestRef.current = false;
          abortRef.current = null;
          setAssistantBusy(false);
          setAssistantPhase('');
        }
      };
      const title = tabs.find(x => x[0] === tab)?.[1] || '';
      const closeWorkspace = () => {
        if (abortRef.current) abortRef.current.abort();
        setMaximized(false);
        setOpen(false);
      };
      const headerButton = { ...S.button, display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'rgba(255,255,255,.055)', color: '#d6e2e7', borderColor: '#3a505b', boxShadow: 'none' };

      const lastMeta = (() => {
        for (let index = assistantMessages.length - 1; index >= 0; index -= 1) {
          const item = assistantMessages[index];
          if (item.role === 'assistant' && item.meta) return item.meta;
        }
        return null;
      })();
      const authoritativeRule = lastMeta && lastMeta.rule
        && (!measurement.measurement_id || lastMeta.measurementId === measurement.measurement_id)
        ? lastMeta.rule : null;
      const engineState = lastMeta ? lastMeta.engine : null;
      const engineText = engineState === 'unavailable' ? '规则引擎不可用'
        : engineState === 'blocked' ? '规则门禁阻断'
          : engineState === 'local-rules' ? '规则引擎在线'
            : engineState === 'none' ? '规则引擎未参与'
              : '规则引擎待校验';
      const engineDot = engineState === 'unavailable' ? '#f87171'
        : engineState === 'blocked' ? '#fbbf24'
          : engineState === 'local-rules' ? '#55d6b6' : '#8fa8b3';
      const engineChip = engineState === 'unavailable'
        ? { background: 'rgba(248,113,113,.12)', color: '#fecaca' }
        : { background: 'rgba(41,180,153,.09)', color: '#8ce0cd' };
      const launcherStyle = embedded ? {
        ...S.launcher, position: 'relative', right: 'auto', bottom: 'auto', zIndex: 'auto', width: '100%',
        boxSizing: 'border-box', padding: '10px 14px', background: '#fff', color: C.ink,
        border: `1px solid ${C.line}`, boxShadow: '0 3px 12px rgba(21,46,56,.06)', borderRadius: 12,
      } : S.launcher;
      const frameStyle = native ? { width: '100%', height: '100%', minHeight: 0, position: 'relative' }
        : embedded ? { width: '100%', position: 'relative', margin: '0 0 10px' }
          : { ...S.mask, padding: maximized ? 0 : 20 };
      const appStyle = native ? {
        ...S.app, position: 'relative', width: '100%', height: '100%', minHeight: 0,
        borderRadius: 0, border: 0, boxShadow: 'none', background: C.bg,
      } : embedded ? {
        ...S.app, position: 'relative', width: '100%', height: maximized ? 'calc(100vh - 156px)' : 'clamp(450px,64vh,700px)',
        minHeight: 0, borderRadius: 14, border: `1px solid ${C.line}`, boxShadow: '0 12px 36px rgba(21,46,56,.12)',
      } : { ...S.app, position: 'relative', width: maximized ? '100vw' : S.app.width,
        height: maximized ? '100vh' : S.app.height, borderRadius: maximized ? 0 : 18,
        boxShadow: maximized ? 'none' : S.app.boxShadow };

      return h(React.Fragment, null,
        !native && (!embedded || !open) && h('button', { style: launcherStyle, onClick: () => setOpen(true), title: '在当前对话中展开创口热成像工作站' },
          h('span', { style: { width: 23, height: 23, borderRadius: 7, background: C.teal, color: '#fff', display: 'grid', placeItems: 'center', fontSize: 17 } }, '+'),
          h('span', null, '创口工作站'),
          embedded && h('span', { style: { marginLeft: 'auto', color: C.muted, fontSize: 11, fontWeight: 500 } }, '在当前对话中展开')),
        (native || open) && h('div', { style: frameStyle, onMouseDown: e => { if (!native && !embedded && e.target === e.currentTarget) closeWorkspace(); } },
          h('section', { style: appStyle, role: native || embedded ? 'region' : 'dialog', 'aria-label': '创口热成像工作站',
            'data-session-id': sessionId || undefined },
            h('header', { style: S.header }, Logo(),
              h('div', { style: { flex: 1 } }, h('div', { style: { fontSize: 17, fontWeight: 700, letterSpacing: '.01em' } }, '创口热成像工作站'),
                h('div', { style: { color: '#8fa8b3', fontSize: 10, letterSpacing: '.11em', marginTop: 2 } }, 'WOUND THERMAL SCREENING & FOLLOW-UP')),
              h('div', { style: { display: 'flex', alignItems: 'center', gap: 7, padding: '5px 10px', borderRadius: 8,
                ...engineChip, fontSize: 11, marginRight: 4 } },
                h('span', { style: { width: 6, height: 6, borderRadius: '50%', background: engineDot } }), engineText),
              h('button', { onClick: toggleAssistant, style: headerButton, title: assistantOpen ? '收起医师角色侧边对话' : '打开医师角色侧边对话',
                'aria-expanded': assistantOpen, 'aria-controls': 'wound-clinic-assistant' },
                Icon({ name: 'assistant', size: 15 }), assistantOpen ? '收起对话' : '循证对话'),
              !native && h(React.Fragment, null,
                h('button', { onClick: () => setMaximized(value => !value), style: headerButton, title: maximized ? '还原工作站高度' : embedded ? '铺满当前对话可用区域' : '进入全屏' },
                  Icon({ name: maximized ? 'collapse' : 'expand', size: 15 }), maximized ? '还原' : embedded ? '铺满' : '全屏'),
                h('button', { onClick: closeWorkspace, style: { ...headerButton, padding: '8px 10px' }, title: embedded ? '收起工作站' : '关闭工作站' },
                  Icon({ name: embedded ? 'panelClose' : 'close', size: 15 }), embedded ? '收起' : '关闭'))),
            h('div', { style: S.body },
              h('nav', { style: S.nav },
                h('div', { style: { ...S.label, padding: '0 11px 12px', fontSize: 10, textTransform: 'uppercase' } }, '工作空间'),
                tabs.map(([id, label]) => {
                  const active = tab === id;
                  return h('button', { key: id, onClick: () => setTab(id), style: {
                    width: '100%', display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
                    border: `1px solid ${active ? '#c9e6df' : 'transparent'}`, borderRadius: 9,
                    padding: '10px 12px', marginBottom: 5,
                    background: active ? C.tealSoft : 'transparent', color: active ? C.teal : '#455c66',
                    fontWeight: active ? 700 : 500, cursor: 'pointer', fontSize: 12 } },
                    Icon({ name: id, size: 16 }), h('span', { style: { flex: 1 } }, label),
                    active && h('span', { style: { width: 5, height: 5, borderRadius: '50%', background: C.teal } }));
                }),
                h('div', { style: { borderTop: `1px solid ${C.line}`, margin: '20px 9px 14px' } }),
                h('div', { style: { padding: '0 10px', fontSize: 10, color: C.muted, lineHeight: '20px' } },
                  h('div', null, `海康设备  ·  ${liveOn && live ? (SOURCE_LABEL[live.source] || '已连接') : '未连接'}`),
                  h('div', null, `温度标定  ·  ${liveOn && live && live.has_temperature ? '实时可用' : '未标定 / 演示有效'}`),
                  h('div', null, '医学证据  ·  4 条已核对')),
                h('div', { style: { margin: '22px 5px 0', padding: '12px 11px', background: '#eef4f4', border: '1px solid #e0eaeb',
                  borderRadius: 10, fontSize: 10, color: C.muted, lineHeight: '18px' } },
                  h('div', { style: { color: C.ink, fontWeight: 650, marginBottom: 3 } }, '本地隐私保护'),
                  '影像默认不外发 · 测量与报告全程留痕')),
              h('div', { style: { flex: 1, minWidth: 0, minHeight: 0, display: 'flex', position: 'relative', overflow: 'hidden' } },
                h('main', { style: S.main },
                  h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 } },
                    h('div', { style: { flex: 1 } }, h('div', { style: { fontSize: 20, fontWeight: 750 } }, title),
                      h('div', { style: { ...S.muted, fontSize: 11 } },
                        tab === 'reports' && activeDraft && draftView === 'detail'
                          ? `${activeDraft.draft_id} / ${activeDraft.measurement_id || '-'}`
                          : `${measurement.patient_ref || '-'} / ${measurement.measurement_id || '-'}`)),
                    h('input', { ref: fileRef, type: 'file', accept: '.json,application/json', style: { display: 'none' }, onChange: importFile }),
                    Button('导入测量 JSON', () => fileRef.current && fileRef.current.click()),
                    Button('保存草稿', openSaveDialog, true, { title: '命名后保存到报告中心' })),
                  notice && h('div', { style: { ...S.card, padding: '9px 13px', marginBottom: 12, color: C.teal, background: C.tealSoft } }, notice),
                  tab === 'screen' && Screen({ measurement, onEvidence: showEvidence, live, liveOn, liveBusy, liveError, liveStamp,
                    liveCfg, onLiveCfg: (key, value) => setLiveCfg(cfg => ({ ...cfg, [key]: value })),
                    onLiveApply: () => void applyLiveConfig(),
                    onConnect: () => void connectLive(false), onDisconnect: () => void disconnectLive(), onCapture: () => void captureLive(),
                    onLiveEngine: (key, value) => void changeLiveEngine(key, value) }),
                  tab === 'archive' && Archive({ patients, activePatient, history: patientHistory, reports: patientReports, onSelect: (ref) => void selectPatient(ref) }),
                  tab === 'trend' && Trend({ measurement, history: activePatient ? patientHistory : [] }),
                  tab === 'reports' && (draftView === 'detail' && activeDraft
                    ? DraftDetail({ draft: activeDraft, title: draftTitle, detailForm, busy: workflowBusy,
                      onTitle: setDraftTitle, onTitleCommit: commitTitle,
                      onField: (key, value) => setDetailForm(form => ({ ...form, [key]: value })),
                      onSaveDetails: saveDetails, onArchive: archiveDraft,
                      onBack: () => { setDraftView('list'); setActiveDraft(null); setPendingDetails(null); draftsLoadedRef.current = false; void loadDrafts(); },
                      onOpenAssistant: () => { setAssistantOpen(true); void ensureRules(); } })
                    : DraftList({ drafts, onOpen: (id) => void openDraft(id), onNew: () => setTab('screen') })),
                  tab === 'evidence' && Evidence({ focus: focusEvidence }),
                  h('footer', { style: { marginTop: 18, paddingTop: 12, borderTop: `1px solid ${C.line}`, color: C.muted, fontSize: 10, display: 'flex', justifyContent: 'space-between' } },
                    h('span', null, '辅助筛查，不替代临床诊断'), h('span', null, 'wound-delta-v1 · local-template-v1'))),
                saveDialog && SaveDraftDialog({ measurement, title: draftTitle, busy: workflowBusy,
                  onTitle: setDraftTitle, onCancel: () => setSaveDialog(false), onSave: saveDraft }),
                assistantOpen && h(AssistantPanel, {
                  messages: assistantMessages,
                  busy: assistantBusy,
                  phase: assistantPhase,
                  error: assistantError,
                  notice: assistantNotice,
                  rules: assistantRules,
                  rulesOpen,
                  input: assistantInput,
                  measurement: activeDraft && tab === 'reports' && draftView === 'detail' ? activeDraft.measurement : measurement,
                  draft: activeDraft && tab === 'reports' && draftView === 'detail' ? activeDraft : null,
                  pendingDetails,
                  maximized,
                  narrow,
                  authoritativeRule,
                  onInput: setAssistantInput,
                  onSend: askAssistant,
                  onQuick: askAssistant,
                  onStop: stopAssistant,
                  onRetry: () => { if (lastQuestionRef.current) void askAssistant(lastQuestionRef.current); },
                  onApplyPending: () => void applyPending(),
                  onDismissPending: () => setPendingDetails(null),
                  onClose: () => {
                    setRulesOpen(false);
                    setAssistantNotice('');
                    setAssistantOpen(false);
                  },
                  onToggleRules: toggleRules,
                  onDismissError: () => setAssistantError(''),
                }),
                !assistantOpen && h('button', {
                  onClick: toggleAssistant,
                  title: '展开循证对话', 'aria-label': '展开循证对话', 'aria-expanded': false,
                  style: { position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', zIndex: 4,
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '12px 8px',
                    border: `1px solid ${C.line}`, borderRight: 0, borderRadius: '10px 0 0 10px', background: '#fff',
                    color: C.teal, boxShadow: '-4px 4px 16px rgba(21,46,56,.08)', cursor: 'pointer',
                    font: '11px/16px system-ui,"Microsoft YaHei",sans-serif', fontWeight: 650 },
                }, Icon({ name: 'assistant', size: 16 }),
                  h('span', { style: { writingMode: 'vertical-rl', letterSpacing: '.12em' } }, '循证对话')))))));
    }

    return {
      inject: ['slots', 'locale'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'wound-clinic: dictionaries');
        const t = ctx.locale.bind(NS);
        // 官方原生主视图：左侧导航选择后，工作站直接占据 DSH 中央主面板。
        ctx.slots.inject('main', () => ctx.slots.register({
          name: 'main', key: 'wound-clinic', locale: NS,
        }, props => h(Workstation, { ...props, native: true })));
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: 'wound-clinic', order: 35, locale: NS,
          label: () => t('open'),
        }, props => Icon({ name: 'screen', size: props.size || 18 })));
      },
    };
  },
});
