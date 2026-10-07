/* Schedule Release: the schedule season's matchups from ESPN, each manager's cards with the pair's
   all-time record, every past meeting (when it happened, the score, the winner's top scorer) and the
   closest / blowout / most recent highlights; a full-schedule list and a grid.

   Reads config.json and data/v1/schedule.json (schema "schedule"); schedule-data.js turns the model
   into the shapes the page's script reads, as the Stage A build wrote them. The script itself is the
   Stage A page's, run inside runPage() once the data is in (decision 7.14: same look first). What was
   written into the page now comes from the league:
     season, title    the model's season; the league's name and its logo for that season
     managers         names, colors (config.json dark colors) and logos; initials when a manager has none
     conferences      each manager's conference that season from ESPN (the model's `conferences`), its
                      color by position in league.conference_labels; no badges without conferences
     week themes      optional, from the league's schedule_themes.yaml; the styles below cover the
                      built-in theme names, any other theme shows its name in the standard style, and
                      the rematch banner / trade count follow what the themes file says a theme shows
     season tint      theme.season_colors for the season */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { url } from '../core/site.js';
import { rgb } from '../core/theme.js';
import { scheduleData } from './schedule-data.js';

var cfg, mgr, SEASON, MANAGERS_DATA, LEAGUE_SCHEDULE, CONF, CONF_LABELS, MANAGER_COLOR;

function logoSrc(name) { var m = mgr.find(name); return m && m.logo ? url(m.logo) : null; }

/* conf-0, conf-1, ... by the label's position among the league's conference labels; "none" without one */
function confClass(name) { var c = CONF[name]; return c ? String(CONF_LABELS.indexOf(c)) : 'none'; }
function confBadge(name, style) {
  var c = CONF[name];
  return c ? '<span class="conf-badge conf-' + confClass(name) + '"' + (style ? ' style="' + style + '"' : '') + '>' + c + '</span>' : '';
}
/* "Jane D." for the grid's row labels; a one-word name stays as it is */
function gridName(n) { var p = n.split(' ').filter(Boolean); return p.length > 1 ? p[0] + ' ' + p[1][0] + '.' : n; }

function runPage() {
  let MANAGERS = [];
  let CURRENT_VIEW = 'my';
  let CURRENT_MANAGER = null;

  const THEME_CLASS = {
    'Rivalry Week':'rivalry','Big Game Week':'biggame','Interconference Week':'inter',
    'Closest Rivalries Week':'closest','Lopsided History Week':'lopsided','Trade Partner Week':'tradeweek'
  };
  const THEME_BANNER_CLASS = {
    'Rivalry Week':'banner-rivalry','Big Game Week':'banner-biggame','Interconference Week':'banner-inter',
    'Closest Rivalries Week':'banner-closest','Lopsided History Week':'banner-lopsided','Trade Partner Week':'banner-tradeweek'
  };
  const THEME_ICON = {
    'Rivalry Week':'&#9876;&#65039;','Big Game Week':'&#127942;','Interconference Week':'&#127775;',
    'Closest Rivalries Week':'&#9878;&#65039;','Lopsided History Week':'&#128293;','Trade Partner Week':'&#129309;'
  };

  function hexToRgb(hex){
    const h = hex.replace('#','');
    const r = parseInt(h.substring(0,2),16);
    const g = parseInt(h.substring(2,4),16);
    const b = parseInt(h.substring(4,6),16);
    return `${r},${g},${b}`;
  }

  function initials(name){ return name.split(' ').filter(Boolean).map(p=>p[0]).join('').slice(0,2); }

  function logoImg(name, size, borderRgb){
    const borderStyle = borderRgb ? `border:3px solid rgb(${borderRgb});` : '';
    const src = logoSrc(name);
    if(!src) return `<div class="logo-fallback" style="width:${size}px;height:${size}px;${borderStyle}">${initials(name)}</div>`;
    return `<img class="logo" src="${src}" style="width:${size}px;height:${size}px;${borderStyle}"
      onerror="this.outerHTML='<div class=&quot;logo-fallback&quot; style=&quot;width:${size}px;height:${size}px;${borderStyle}&quot;>${initials(name)}</div>'">`;
  }

  function hashStr(s){
    let h=0;
    for(let i=0;i<s.length;i++){ h = (h*31 + s.charCodeAt(i)) % 1000; }
    return h;
  }

  function seasonLabel(g){
    if(g.week.startsWith('Playoff')) return g.season+' playoffs';
    return "'"+g.season.slice(2)+' '+g.week.replace('Week ','Wk ');
  }
  function h2hLabel(g){
    const yr = "'"+String(g.season).slice(2);
    return g.label.startsWith('Week') ? yr+' '+g.label.replace('Week ','Wk ') : yr+' '+g.label;
  }
  function fmtScore(n){ return n.toFixed(1); }

  function generateCaption(entry, meName){
    const {my_wins, opp_wins, total_games, closest, blowout} = entry;
    const opp = entry.opponent;
    const h = hashStr(meName+opp+entry.week);

    if(total_games===0){
      const opts = [
        "No history here. First-ever meeting, clean slate.",
        "Uncharted territory. These two have never lined up before.",
        "Brand new beef. Nothing on the scoreboard yet."
      ];
      return opts[h%opts.length];
    }

    const diff = my_wins - opp_wins;
    let base;
    if(Math.abs(diff) <= 1 && total_games>=4){
      const opts = [
        `Dead even at ${my_wins}-${opp_wins}. About as balanced as this league gets.`,
        `Razor-thin all-time, ${my_wins}-${opp_wins}. Anyone's series.`,
        `${my_wins}-${opp_wins} all-time, a genuine coin flip.`
      ];
      base = opts[h%opts.length];
    } else if(diff >= 4 || (total_games>=5 && my_wins/total_games>=0.72)){
      const opts = [
        `You've owned this one, ${my_wins}-${opp_wins} all-time.`,
        `Total domination so far: ${my_wins}-${opp_wins} in your favor.`,
        `${my_wins}-${opp_wins}. This series isn't close.`
      ];
      base = opts[h%opts.length];
    } else if(diff <= -4 || (total_games>=5 && opp_wins/total_games>=0.72)){
      const opts = [
        `They've had your number: ${opp_wins}-${my_wins} all-time.`,
        `Not your series, ${opp} leads ${opp_wins}-${my_wins}.`,
        `${opp_wins}-${my_wins} in their favor. Time for a correction?`
      ];
      base = opts[h%opts.length];
    } else {
      const leaderMe = diff>0;
      const opts = leaderMe ? [
        `You're up ${my_wins}-${opp_wins}, but it's not settled.`,
        `Slight edge for you, ${my_wins}-${opp_wins} all-time.`
      ] : [
        `${opp} holds a ${opp_wins}-${my_wins} edge, for now.`,
        `They're up ${opp_wins}-${my_wins} all-time. Room to close the gap.`
      ];
      base = opts[h%opts.length];
    }

    let extra = '';
    if(closest && closest.margin < 4){
      extra = ` Their closest game ever came down to ${closest.margin} points, ${closest.winner} won it, in ${seasonLabel(closest)}.`;
    } else if(blowout && blowout.margin > 70){
      extra = ` Also home to the ugliest blowout between them: ${blowout.margin} points (${seasonLabel(blowout)}).`;
    }
    return base + extra;
  }

  function bannerFor(entry){
    const wt = entry.week_type;
    // a theme whose cards show the pair's biggest playoff meeting (schedule_themes.yaml `rematch`)
    if(entry.rematch) return {html:`<div class="ticket-banner banner-biggame">&#127942; ${entry.rematch.season} ${entry.rematch.round} Rematch</div>`};
    if(wt==='Rivalry Week') return {html:`<div class="ticket-banner banner-rivalry">&#9876;&#65039; Rivalry Week</div>`};
    if(wt==='Big Game Week'){
      const label = entry.rematch ? `${entry.rematch.season} ${entry.rematch.round} Rematch` : 'Big Game Week';
      return {html:`<div class="ticket-banner banner-biggame">&#127942; ${label}</div>`};
    }
    if(wt==='Interconference Week') return {html:`<div class="ticket-banner banner-inter">&#127775; Interconference Week</div>`};
    if(wt==='Closest Rivalries Week') return {html:`<div class="ticket-banner banner-closest">&#9878;&#65039; Closest Rivalries Week</div>`};
    if(wt==='Lopsided History Week') return {html:`<div class="ticket-banner banner-lopsided">&#128293; Lopsided History Week</div>`};
    if(wt==='Trade Partner Week') return {html:`<div class="ticket-banner banner-tradeweek">&#129309; Trade Partner Week</div>`};
    // a theme without a built-in style shows its name
    if(wt!=='Standard') return {html:`<div class="ticket-banner banner-standard">${wt}</div>`};
    return {html:`<div class="ticket-banner banner-standard">Week ${entry.week}</div>`};
  }

  const THEME_HEADER_CLASS = {
    'Rivalry Week':'theme-header-rivalry','Big Game Week':'theme-header-biggame','Interconference Week':'theme-header-inter',
    'Closest Rivalries Week':'theme-header-closest','Lopsided History Week':'theme-header-lopsided','Trade Partner Week':'theme-header-tradeweek'
  };
  const THEME_SHORT_LABEL = {
    'Rivalry Week':'RIVAL','Big Game Week':'BIG GAME','Interconference Week':'X-CONF',
    'Closest Rivalries Week':'CLOSEST','Lopsided History Week':'LOPSIDED','Trade Partner Week':'TRADES'
  };

  function renderGridSchedule(){
    const content = document.getElementById('content');
    content.className = 'carousel-wrap';

    const oppByTeamWeek = {};
    MANAGERS.forEach(m=> oppByTeamWeek[m] = {});
    LEAGUE_SCHEDULE.forEach(wk=>{
      wk.matchups.forEach(m=>{
        oppByTeamWeek[m.team_a][wk.week] = m.team_b;
        oppByTeamWeek[m.team_b][wk.week] = m.team_a;
      });
    });

    let html = `<div class="grid-wrap"><table class="schedule-grid"><thead><tr>
      <th class="grid-corner"></th>`;
    LEAGUE_SCHEDULE.forEach(wk=>{
      const headerClass = THEME_HEADER_CLASS[wk.week_type] || 'theme-header-standard';
      const shortLabel = THEME_SHORT_LABEL[wk.week_type] || '';
      html += `<th class="grid-week-header ${headerClass}">
        <div class="grid-week-num">W${wk.week}</div>
        ${shortLabel ? `<div class="grid-week-theme">${shortLabel}</div>` : ''}
      </th>`;
    });
    html += `</tr></thead><tbody>`;

    MANAGERS.forEach(team=>{
      html += `<tr>
        <td class="grid-team-header">
          <div class="grid-team-header-inner">${logoImg(team, 20)}<span class="grid-team-name">${gridName(team)}</span></div>
        </td>`;
      LEAGUE_SCHEDULE.forEach(wk=>{
        const opp = oppByTeamWeek[team][wk.week];
        const oppConf = confClass(opp);
        html += `<td class="grid-cell conf-cell-${oppConf}" onclick="jumpToManagerWeek('${team}', ${wk.week})">${logoImg(opp, 26)}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table></div>`;
    content.innerHTML = html;
  }

  function renderLeagueSchedule(){
    const content = document.getElementById('content');
    content.className = 'carousel-wrap';
    let html = `<div class="league-schedule">`;
    LEAGUE_SCHEDULE.forEach(wk=>{
      const bannerClass = THEME_BANNER_CLASS[wk.week_type] || 'banner-standard';
      const themeClass = THEME_CLASS[wk.week_type] || 'standard';
      const icon = THEME_ICON[wk.week_type] || '';
      const label = wk.week_type==='Standard' ? `Week ${wk.week}` : `${icon} ${wk.week_type}`;
      html += `<div class="league-week-card ${themeClass}">
        <div class="league-week-banner ${bannerClass}">${label}${wk.week_type!=='Standard' ? ' &middot; Week '+wk.week : ''}</div>
        <div class="league-matchup-list">`;
      wk.matchups.forEach(m=>{
        html += `<div class="league-matchup-row">
          <div class="league-team-tap conf-${confClass(m.team_a)}" onclick="jumpToManagerWeek('${m.team_a}', ${wk.week})">
            ${logoImg(m.team_a, 22)}
            <span class="league-matchup-name">${m.team_a}</span>
          </div>
          <span class="league-vs">VS</span>
          <div class="league-team-tap league-team-tap-right conf-${confClass(m.team_b)}" onclick="jumpToManagerWeek('${m.team_b}', ${wk.week})">
            <span class="league-matchup-name" style="text-align:right">${m.team_b}</span>
            ${logoImg(m.team_b, 22)}
          </div>
          ${m.interconference ? `<span class="league-cross-tag">X-CONF</span>` : ''}
        </div>`;
      });
      html += `</div></div>`;
    });
    html += `</div>`;
    content.innerHTML = html;
  }

  function setView(view){
    CURRENT_VIEW = view;
    document.querySelectorAll('.toggle-btn').forEach(b=>{
      b.classList.toggle('active', b.dataset.view===view);
    });
    const managerRow = document.getElementById('managerRow');
    if(view==='league'){
      managerRow.style.display = 'none';
      renderLeagueSchedule();
    } else if(view==='grid'){
      managerRow.style.display = 'none';
      renderGridSchedule();
    } else {
      managerRow.style.display = 'flex';
      if(CURRENT_MANAGER){
        selectManager(CURRENT_MANAGER);
      } else {
        document.getElementById('content').className = 'carousel-wrap';
        document.getElementById('content').innerHTML = `
          <div class="placeholder">
            <div class="placeholder-emoji">${SEASON}</div>
            <div class="placeholder-text">Tap your name up top to pull up your full schedule, rivalry history, and the games with real history behind them.</div>
          </div>`;
      }
    }
  }

  function renderManagerChips(selected){
    const row = document.getElementById('managerRow');
    row.innerHTML = '';
    MANAGERS.forEach(m=>{
      const chip = document.createElement('div');
      const isActive = m===selected;
      chip.className = 'chip' + (isActive ? ' active' : '');
      if(!isActive){
        const c = MANAGER_COLOR[m] || '107,90,108';
        chip.style.background = `rgba(${c},0.14)`;
        chip.style.borderColor = `rgba(${c},0.45)`;
      }
      chip.innerHTML = logoImg(m, 20) + '<span>' + m.split(' ')[0] + '</span>';
      chip.onclick = ()=> selectManager(m);
      row.appendChild(chip);
    });
  }

  function renderTicket(entry, meName){
    const themeClassMap = {
      'Rivalry Week':'rivalry','Big Game Week':'biggame','Interconference Week':'inter',
      'Closest Rivalries Week':'closest','Lopsided History Week':'lopsided','Trade Partner Week':'tradeweek'
    };
    const tClass = themeClassMap[entry.week_type] || '';
    const oppConf = confClass(entry.opponent);

    const dots = entry.game_log.map(r => `<div class="rdot ${r==='win'?'win':'loss'}"></div>`).join('');

    const record = entry.total_games===0
      ? 'First meeting'
      : `<span style="color:var(--win)">${entry.my_wins}</span>-<span style="color:var(--loss)">${entry.opp_wins}</span> <span style="color:var(--ink-soft); font-weight:500;">all-time</span>`;

    const gameCount = entry.games ? entry.games.length : 0;
    const h2hLabel_ = `<div class="h2h-section-label">Head-to-Head History${gameCount ? ` &middot; ${gameCount} game${gameCount===1?'':'s'}` : ''}</div>`;
    const h2hHistory = (entry.games && entry.games.length)
      ? `${h2hLabel_}
         <div class="h2h-history">${entry.games.map(g => {
          const iWon = g.winner === meName;
          const mvpColor = MANAGER_COLOR[g.winner] || '107,90,108';
          const mvpHtml = g.mvp_name
            ? `<div class="h2h-mvp">
                <span class="h2h-mvp-star">&#11088;</span>
                <span class="h2h-mvp-name" style="background:rgba(${mvpColor},0.22)">${g.mvp_name}</span>
                <span class="h2h-mvp-pts">${fmtScore(g.mvp_pts)}</span>
              </div>`
            : '';
          return `<div class="h2h-game">
            <div class="h2h-row">
              <div class="h2h-label">${h2hLabel(g)}</div>
              <div class="h2h-score">
                <span style="color:${iWon?'var(--win)':'var(--loss)'}">${fmtScore(g.score_a)}</span><span class="h2h-dash">-</span><span style="color:${iWon?'var(--loss)':'var(--win)'}">${fmtScore(g.score_b)}</span>
              </div>
            </div>
            ${mvpHtml}
          </div>`;
        }).join('')}</div>`
      : `${h2hLabel_}<div class="h2h-empty">First meeting - no history yet.</div>`;

    const caption = generateCaption(entry, meName);
    const interNote = entry.week_type==='Interconference Week'
      ? `<div class="inter-note">Every matchup across the league this week is ${CONF_LABELS.join(' vs. ')}.</div>` : '';
    const bigGameNote = entry.week_type==='Big Game Week'
      ? `<div class="inter-note">This week across the league is Big Game Week: championship and playoff rematches from throughout league history.</div>` : '';
    const closestNote = entry.week_type==='Closest Rivalries Week'
      ? `<div class="inter-note">Every matchup across the league this week is a dead-even, all-time series.</div>` : '';
    const lopsidedNote = entry.week_type==='Lopsided History Week'
      ? `<div class="inter-note">Every matchup across the league this week is the most one-sided series either manager has.</div>` : '';
    const tradeweekNote = entry.week_type==='Trade Partner Week'
      ? `<div class="inter-note">Every matchup this week has traded with each other at least once, though not always their single most frequent partner.</div>` : '';
    const banner = bannerFor(entry);
    const colorA = MANAGER_COLOR[meName] || '107,90,108';
    const colorB = MANAGER_COLOR[entry.opponent] || '107,90,108';
    const ticketBg = `background:linear-gradient(150deg, rgba(${colorA},0.22), rgba(${colorB},0.22) 60%, #fff 100%);`;

    return `
    <div class="ticket-slide">
      <div class="ticket ${tClass}" style="${ticketBg}">
        <div class="ticket-dim"></div>
        ${banner.html}
        <div class="ticket-body">
          <div class="week-tag">Week ${entry.week}</div>
          ${interNote}
          ${bigGameNote}
          ${closestNote}
          ${lopsidedNote}
          ${tradeweekNote}
          <div class="matchup-row">
            <div class="logo-halo halo-${confClass(meName)}">${logoImg(meName, 72, MANAGER_COLOR[meName])}</div>
            <div class="matchup-vs">VS</div>
            <div class="logo-halo halo-${oppConf}">${logoImg(entry.opponent, 72, MANAGER_COLOR[entry.opponent])}</div>
          </div>
          <div class="matchup-names">
            <div class="matchup-name">${meName}</div>
            <div class="matchup-name">${entry.opponent}</div>
          </div>
          <div class="stat-line"><span class="stat-label">Series</span><span class="stat-value">${record}</span>
            ${confBadge(entry.opponent, 'margin-left:auto')}</div>
          ${entry.trade_count ? `<div class="stat-line"><span class="stat-label">Trades</span><span class="stat-value">${entry.trade_count} all-time trade${entry.trade_count===1?'':'s'} between them</span></div>` : ''}
          ${h2hHistory}
        </div>
      </div>
    </div>`;
  }

  function jumpToManagerWeek(name, week){
    CURRENT_VIEW = 'my';
    document.querySelectorAll('.toggle-btn').forEach(b=>{
      b.classList.toggle('active', b.dataset.view==='my');
    });
    document.getElementById('managerRow').style.display = 'flex';
    selectManager(name);
    requestAnimationFrame(()=>{
      const schedule = MANAGERS_DATA[name];
      const idx = schedule.findIndex(e => e.week === week);
      const carousel = document.getElementById('carousel');
      if(carousel && idx >= 0){
        const slides = carousel.querySelectorAll('.ticket-slide');
        if(slides[idx]) slides[idx].scrollIntoView({behavior:'instant', inline:'start', block:'nearest'});
      }
    });
  }

  function selectManager(name){
    CURRENT_MANAGER = name;
    renderManagerChips(name);
    const content = document.getElementById('content');
    content.className = 'carousel-wrap';
    const schedule = MANAGERS_DATA[name];

    let html = `
      <div class="season-strip">
        <div class="season-name-row">
          ${logoImg(name, 30)}
          <div class="season-name">${name}</div>
        </div>
        ${confBadge(name)}
      </div>
      <div class="swipe-hint">Swipe to move through the season &rarr;</div>
      <div class="carousel" id="carousel">`;

    schedule.forEach(entry=>{ html += renderTicket(entry, name); });
    html += `</div><div class="progress" id="progress"></div>`;
    content.innerHTML = html;

    const progress = document.getElementById('progress');
    schedule.forEach((_,i)=>{
      const d = document.createElement('div');
      d.className = 'pdot' + (i===0 ? ' active' : '');
      progress.appendChild(d);
    });

    const carousel = document.getElementById('carousel');
    const slides = carousel.querySelectorAll('.ticket-slide');
    const tickets = carousel.querySelectorAll('.ticket');
    const dots = progress.querySelectorAll('.pdot');

    // Only show the "scroll for more" fade/chevron on cards that actually
    // overflow -- a card whose history already fits shouldn't hint at
    // scrolling that doesn't exist. Re-checked on resize since rotating a
    // device or opening the on-screen keyboard changes available height.
    function markScrollableTickets(){
      tickets.forEach(t=>{
        const body = t.querySelector('.ticket-body');
        if(!body) return;
        t.classList.toggle('has-more-scroll', body.scrollHeight > body.clientHeight + 2);
      });
    }
    markScrollableTickets();
    window.addEventListener('resize', markScrollableTickets);

    const observer = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        const idx = Array.from(slides).indexOf(e.target);
        const ticketEl = tickets[idx];
        if(e.isIntersecting && e.intersectionRatio > 0.6){
          ticketEl.classList.add('active-card');
          dots.forEach((d,i)=> d.classList.toggle('active', i===idx));
        } else {
          ticketEl.classList.remove('active-card');
        }
      });
    }, {root: carousel, threshold:[0.6]});
    slides.forEach(s=>observer.observe(s));
  }


    MANAGERS = Object.keys(MANAGERS_DATA).sort((a,b)=> a.split(' ')[0].localeCompare(b.split(' ')[0]));
    renderManagerChips(null);
    document.getElementById('content').innerHTML = `
      <div class="placeholder">
        <div class="placeholder-emoji">${SEASON}</div>
        <div class="placeholder-text">Tap your name up top to pull up your full schedule, rivalry history, and the games with real history behind them.</div>
      </div>`;
    document.querySelectorAll('.toggle-btn').forEach(btn=>{
      btn.onclick = ()=> setView(btn.dataset.view);
    });

  // the handler the page's markup names (inline onclick, as on the Stage A page)
  Object.assign(window, { jumpToManagerWeek });
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  return load('data/v1/schedule.json');
}).then(function (M) {
  var D = scheduleData(M, mgr.name);
  SEASON = D.SEASON; MANAGERS_DATA = D.MANAGERS_DATA; LEAGUE_SCHEDULE = D.LEAGUE_SCHEDULE; CONF = D.CONF;
  var labels = Object.values((cfg.league && cfg.league.conference_labels) || {});
  CONF_LABELS = labels.concat(Array.from(new Set(Object.values(CONF))).filter(function (l) { return labels.indexOf(l) === -1; }).sort())
    .filter(function (l) { return Object.values(CONF).indexOf(l) !== -1; });
  MANAGER_COLOR = {};
  mgr.all.forEach(function (m) { if (m.colors && m.colors.dark) MANAGER_COLOR[m.name] = rgb(m.colors.dark); });

  var league = cfg.league || {};
  var logo = (league.logos_by_season || {})[String(SEASON)] || league.logo;
  document.title = (league.name ? league.name + ': ' : '') + SEASON + ' Schedule Release';
  document.getElementById('brand-sub').innerHTML = (league.name ? league.name + ' &middot; ' : '') + 'Season ' + SEASON;
  var hero = document.getElementById('hero-logo');
  if (logo) { hero.src = url(logo); hero.onerror = function () { hero.remove(); }; document.getElementById('favicon').href = url(logo); }
  else hero.remove();
  var tint = cfg.theme && cfg.theme.season_colors && cfg.theme.season_colors[String(SEASON)];
  if (tint) {
    document.documentElement.style.setProperty('--year-accent', tint);
    document.documentElement.style.setProperty('--year-rgb', rgb(tint));
  }
  runPage();
}).catch(function (err) {
  console.error(err);
  document.getElementById('content').innerHTML = `<div class="placeholder"><div class="placeholder-text">Couldn't load the schedule.</div></div>`;
});
