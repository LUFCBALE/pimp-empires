
(function(){

  const STORAGE_KEY = 'pimpempires-save';

  let state = null;

  function getStock(item){
    // stockKey may be a dotted path like "guns.pistol9mm"
    return item.stockKey.split('.').reduce((v, p) => (v || {})[p], state) || 0;
  }



  function defaultState(){
    const randomCity = CITIES[Math.floor(Math.random() * CITIES.length)];
    return {
      name: 'Big Boss',
      gang: '',
      cash: 500,
      hoes: 1,
      thugs: 0,
      turns: 4000,
      maxTurns: 4000,
      lastRegen: Date.now(),
      hoeMorale: 50,
      thugMorale: 50,
      workLocation: 'redlight',
      location: randomCity.name,
      gunsStock: 0,
      guns: {
        pistol9mm: 0,
        shotgun12gauge: 0,
        ak47: 0,
        m249: 0,
      },
      cadillacs: 0,
      armoredTrucks: 0,
      medsStock: 0,
      factories: { medical: 0, gun: 0, car: 0, drug: 0, explosive: 0, counterfeit: 0, gym: 0, warehouse: 0 },
      bombs: 0,
      lastFactoryRun: Date.now(),
      market: {
        guns: {mult:1, history:[1]},
        meds: {mult:1, history:[1]},
        cars: {mult:1, history:[1]},
      },
      lastMarketUpdate: Date.now(),
      lastCasinoHeist: 0,
      lastJobHeist: 0,
      bribeActiveUntil: 0,
      bribeCooldownUntil: 0,
      bots: [],
      crewMembers: [],
      drugs: {weed: 0, coke: 0, heroin: 0, ecstasy: 0, lsd: 0, meth: 0, xanax: 0, ketamine: 0, mdma: 0},
      dealerPrices: {},
      dealerBoughtToday: {},
      drugBoughtAt: {},
      drugsPaidPrice: {},
      lastDealerPriceUpdate: Date.now(),
      gameStartTime: Date.now(),
      last24HourBonus: Date.now(),
      lastRealMoneyPurchase: 0,
      mobDollars: 0,
      showWorkResults: false,
      messages: [],
      log: [{t:'SYSTEM', msg:'Welcome back to the block. One hoe, a little cash, and a dream. Get to work.', cls:'info'}],
    };
  }

  // Auth system
  let currentUser = null;

  // A referral link is just "?ref=<userId>" tacked onto the homepage URL -
  // grab it once on load so it's ready to send along with a sign-up.
  const pendingReferralCode = new URLSearchParams(window.location.search).get('ref');

  async function initAuth(){
    // Auth is a server-side session (cookie), not something we can read
    // from localStorage - ask the server who, if anyone, is logged in.
    try{
      const res = await fetch('/api/me');
      const data = await res.json();
      currentUser = data.loggedIn ? data.user : null;
    } catch(e){
      currentUser = null;
    }
    updateAuthUI();
  }

  function signUp(){
    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value;
    const pimpId = document.getElementById('authPimpId').value.trim();

    if(!email || !password || !pimpId){
      showToast('Email, password, and Pimp Name required');
      return;
    }

    if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){
      showToast('Invalid email address');
      return;
    }

    if(password.length < 6){
      showToast('Password must be at least 6 characters');
      return;
    }

    if(pimpId.length < 3 || pimpId.length > 20){
      showToast('Pimp Name must be 3-20 characters');
      return;
    }

    // Check if email already exists
    const accounts = JSON.parse(localStorage.getItem('pimpempires-accounts') || '{}');
    if(accounts[email]){
      showToast('Email already registered');
      return;
    }

    // Create new account
    accounts[email] = {email, pimpName: pimpId, password, createdAt: Date.now()};
    localStorage.setItem('pimpempires-accounts', JSON.stringify(accounts));

    // Sign in the new user
    currentUser = {email, pimpName: pimpId};
    localStorage.setItem('pimpempires-auth', JSON.stringify(currentUser));

    state.name = pimpId;
    save();

    showToast(`Welcome ${pimpId}! Your Pimp Name is locked forever.`);
    document.getElementById('authModal').style.display = 'none';
    updateAuthUI();
    render();
  }

  function signIn(){
    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value;

    if(!email || !password){
      showToast('Email and password required');
      return;
    }

    const accounts = JSON.parse(localStorage.getItem('pimpempires-accounts') || '{}');
    if(!accounts[email]){
      showToast('Email not found. Sign up first!');
      return;
    }

    if(accounts[email].password !== password){
      showToast('Incorrect password');
      return;
    }

    currentUser = {email, pimpName: accounts[email].pimpName};
    localStorage.setItem('pimpempires-auth', JSON.stringify(currentUser));

    showToast(`Welcome back, ${currentUser.pimpName}!`);
    document.getElementById('authModal').style.display = 'none';
    updateAuthUI();
    load();
  }

  async function signOut(){
    try{ await fetch('/api/logout', {method: 'POST'}); } catch(e){ /* ignore */ }
    currentUser = null;
    state = defaultState();
    updateAuthUI();
    render();
    showToast('Signed out');
  }

  function updateAuthUI(){
    const homepage = document.getElementById('homepage');
    const gameContainer = document.getElementById('gameContainer');
    const authDisplay = document.getElementById('authDisplay');
    const authToggleBtn = document.getElementById('authToggleBtn');

    if(currentUser){
      // Show game, hide homepage
      if(homepage) homepage.style.display = 'none';
      if(gameContainer) gameContainer.style.display = 'flex';
      if(window.updateTopStripOffset) requestAnimationFrame(window.updateTopStripOffset);

      authDisplay.textContent = `Logged in: ${currentUser.pimpName}`;
      authDisplay.style.color = 'var(--teal)';
      authDisplay.style.cursor = 'pointer';
      authDisplay.title = 'View your profile';
      authDisplay.onclick = openOwnProfile;
      authToggleBtn.textContent = '🔑 Sign Out';
      authToggleBtn.onclick = signOut;
      connectLiveSocket();
    } else {
      // Show homepage, hide game
      if(homepage) homepage.style.display = 'flex';
      if(gameContainer) gameContainer.style.display = 'none';

      authDisplay.textContent = 'Not logged in';
      authDisplay.style.color = 'var(--gold)';
      authToggleBtn.textContent = '🔑 Sign Up / Login';
      authToggleBtn.onclick = () => showAuthModal(true);
      disconnectLiveSocket();
    }
  }

  // Shared with the music mute toggle - one master switch for all in-game
  // sound, music or SFX.
  function isSoundMuted(){
    return localStorage.getItem('pimpempires-music-muted') === 'true';
  }

  function playAttackAlert(){
    if(isSoundMuted()) return;
    const sfx = document.getElementById('attackAlertSound');
    if(!sfx) return;
    sfx.currentTime = 0;
    sfx.volume = 1.0;
    sfx.play().catch(() => {});
  }

  // Push layer: instant notifications for DMs/crew invites/attacks instead
  // of waiting up to 20s for the next poll. Falls back gracefully - if the
  // socket never connects (offline, blocked, etc.) the existing polling in
  // syncState() still keeps everything eventually consistent.
  let liveSocket = null;
  function connectLiveSocket(){
    if(liveSocket) return;
    liveSocket = io();
    liveSocket.on('dm', (data) => { if(data.text) showToast(`✉️ ${data.text}`); syncState(); });
    liveSocket.on('attacked', (data) => { if(data.text) showToast(`💥 ${data.text}`); playAttackAlert(); syncState(); });
    liveSocket.on('crewChat', () => { syncState(); });
    liveSocket.on('globalChat', () => { syncState(); });
    liveSocket.on('theJobUpdate', () => { syncState(); });
  }
  function disconnectLiveSocket(){
    if(liveSocket){ liveSocket.disconnect(); liveSocket = null; }
  }

  // ---- Web Push (attack alerts - works even with the game closed) ----
  // Fetched from the server rather than hardcoded, since the key only
  // exists once the server generates/persists its own VAPID pair.
  let vapidPublicKeyCache = null;
  async function getVapidPublicKey(){
    if(vapidPublicKeyCache) return vapidPublicKeyCache;
    const res = await fetch('/api/push/vapid-public-key');
    const data = await res.json();
    vapidPublicKeyCache = data.publicKey;
    return vapidPublicKeyCache;
  }

  function urlBase64ToUint8Array(base64String){
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    const out = new Uint8Array(rawData.length);
    for(let i = 0; i < rawData.length; i++) out[i] = rawData.charCodeAt(i);
    return out;
  }

  function registerServiceWorker(){
    if(!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('./sw.js').then(() => updatePushToggleBtn()).catch(() => {});
  }

  function pushSupported(){
    return 'serviceWorker' in navigator && 'PushManager' in window;
  }

  async function getPushSubscription(){
    if(!pushSupported()) return null;
    try{
      const reg = await navigator.serviceWorker.ready;
      return await reg.pushManager.getSubscription();
    } catch(e){ return null; }
  }

  async function updatePushToggleBtn(){
    const btn = document.getElementById('pushToggleBtn');
    if(!btn) return;
    if(!pushSupported()){
      btn.textContent = 'Not supported';
      btn.disabled = true;
      return;
    }
    btn.disabled = false;
    const sub = await getPushSubscription();
    btn.textContent = sub ? 'Disable' : 'Enable';
  }

  async function enablePushNotifications(){
    try{
      const permission = await Notification.requestPermission();
      if(permission !== 'granted'){
        showToast('Notifications blocked — allow them in your browser/OS settings to use this');
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const publicKey = await getVapidPublicKey();
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      await apiCall('/api/push/subscribe', sub.toJSON());
      showToast('🔫 Attack alerts enabled');
    } catch(e){
      showToast('Could not enable attack alerts');
    }
    updatePushToggleBtn();
  }

  async function disablePushNotifications(){
    try{
      const sub = await getPushSubscription();
      if(sub){
        await apiCall('/api/push/unsubscribe', {endpoint: sub.endpoint});
        await sub.unsubscribe();
      }
      showToast('Attack alerts disabled');
    } catch(e){ /* best-effort */ }
    updatePushToggleBtn();
  }

  registerServiceWorker();

  function showAuthModal(isSignUp){
    const modal = document.getElementById('authModal');
    const title = document.getElementById('authTitle');
    const emailInput = document.getElementById('authEmail');
    const passwordInput = document.getElementById('authPassword');
    const pimpIdInput = document.getElementById('authPimpId');
    const pimpIdDiv = document.getElementById('authPimpIdDiv');
    const submitBtn = document.getElementById('authSubmitBtn');
    const toggleBtn = document.getElementById('authToggleModalBtn');

    emailInput.value = '';
    passwordInput.value = '';
    pimpIdInput.value = '';

    if(isSignUp){
      title.textContent = 'Create Your Empire';
      pimpIdDiv.style.display = 'block';
      submitBtn.textContent = 'Sign Up';
      submitBtn.onclick = signUp;
      toggleBtn.textContent = 'Already have an account? Sign In';
    } else {
      title.textContent = 'Welcome Back';
      pimpIdDiv.style.display = 'none';
      submitBtn.textContent = 'Sign In';
      submitBtn.onclick = signIn;
      toggleBtn.textContent = 'New? Create an account';
    }

    modal.style.display = 'flex';
  }

  // The server (Flask + game_engine.py) is now the single source of truth
  // for all game state and math. The client only ever displays `state` and
  // sends action requests; it never computes outcomes locally anymore.
  async function apiCall(url, body){
    const opts = {method: 'POST', headers: {'Content-Type': 'application/json'}};
    if(body !== undefined) opts.body = JSON.stringify(body);
    let res, data;
    try{
      res = await fetch(url, opts);
      data = await res.json();
    } catch(e){
      showToast('Connection error');
      throw e;
    }
    if(!data.success){
      showToast(data.error || 'Something went wrong');
      throw new Error(data.error || 'request failed');
    }
    if(data.state){
      const before = new Set((state && state.achievements) || []);
      state = data.state;
      (state.achievements || []).forEach(id => {
        if(!before.has(id)){
          const a = ACHIEVEMENTS_BY_ID[id];
          if(a) showToast(`🏆 Achievement unlocked: ${a.emoji} ${a.name} (+${a.xp} XP)`);
        }
      });
    }
    return data;
  }

  // Homepage sign-up / sign-in. Exposed on window because these are
  // invoked from inline onclick="" attributes, which run in global scope
  // and can't see functions declared privately inside this closure.
  window.homeSignUp = async function(){
    const email = document.getElementById('homeAuthEmail').value.trim();
    const pass = document.getElementById('homeAuthPassword').value;
    const pimpName = document.getElementById('homeAuthPimpName').value.trim();
    if(!email || !pass || !pimpName){
      alert('All fields required');
      return;
    }
    let data;
    try{
      const res = await fetch('/api/signup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password: pass, pimpName, referredBy: pendingReferralCode})
      });
      data = await res.json();
    } catch(e){
      alert('Connection error: ' + e.message);
      return;
    }
    if(data.error){
      alert('Error: ' + data.error);
      return;
    }
    currentUser = data.user;
    if(data.state) state = data.state;
    updateAuthUI();
    render();
    maybeShowTutorial();
  };

  window.homeSignInSubmit = async function(){
    const email = document.getElementById('homeSignInEmail').value.trim();
    const pass = document.getElementById('homeSignInPassword').value;
    if(!email || !pass){
      alert('Email and password required');
      return;
    }
    let data;
    try{
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password: pass})
      });
      data = await res.json();
    } catch(e){
      alert('Connection error: ' + e.message);
      return;
    }
    if(data.error){
      alert('Error: ' + data.error);
      return;
    }
    currentUser = data.user;
    if(data.state) state = data.state;
    updateAuthUI();
    render();
    maybeShowTutorial();
  };

  async function load(){
    try{
      const res = await fetch('/api/state');
      const data = await res.json();
      if(data.success && data.state){
        state = data.state;
        render();
        return;
      }
    } catch(e){
      console.error('Failed to load state from server:', e);
    }
    state = defaultState();
    render();
  }

  // Kept as a no-op shim: every gameplay action now saves itself server-side
  // via apiCall(). Nothing in the client should mutate `state` directly
  // anymore, so there is nothing left for this to persist.
  async function save(){}



  function ensureMarket(){
    if(!state.market) state.market = {};
    BLACKMARKET_ITEMS.forEach(item => {
      if(!state.market[item.key]) state.market[item.key] = {mult:1, history:[1]};
    });
    if(!state.lastMarketUpdate) state.lastMarketUpdate = Date.now();
  }

  function stepMarketItem(key){
    const m = state.market[key];
    const drift = 0.85 + Math.random() * 0.3; // ±15% per hourly step
    m.mult = Math.max(MARKET_MIN_MULT, Math.min(MARKET_MAX_MULT, m.mult * drift));
    m.history.push(m.mult);
    if(m.history.length > MARKET_HISTORY_CAP) m.history.shift();
  }

  function tickMarket(){
    ensureMarket();
    const now = Date.now();
    const elapsed = now - state.lastMarketUpdate;
    const ticks = Math.floor(elapsed / MARKET_MS);
    if(ticks < 1) return false;
    const steps = Math.min(ticks, MARKET_HISTORY_CAP);
    for(let i=0; i<steps; i++){
      BLACKMARKET_ITEMS.forEach(item => stepMarketItem(item.key));
    }
    state.lastMarketUpdate += ticks * MARKET_MS;
    return true;
  }

  function currentPrice(item){
    // Thugs have fixed sell price of 90
    if(item.key === 'thugs') return 90;
    ensureMarket();
    const mult = (state.market[item.key] && state.market[item.key].mult) || 1;
    // Capped below 1.0 (not at 1.0) so a buy-then-sell round trip always
    // costs real cash, never a wash - must match _market_current_price in
    // game_engine.py exactly, or this preview price will lie to the player.
    return Math.max(1, Math.round(item.price * Math.min(mult, 0.9)));
  }

  function thugBuyPrice(){
    // Thugs get pricier the bigger your hoe roster gets: £100 at 0 hoes,
    // £300 at 500, £1,000 at 1,000 hoes - then it caps there.
    const hoes = Math.min(state.hoes || 0, 1000);
    const price = (hoes * (hoes - 100)) / 1000 + 100;
    return Math.max(100, Math.round(price));
  }

  function bribeCost(){
    return Math.round((state.hoes || 0) * BRIBE_COST_PER_HOE);
  }

  async function bribeCops(){
    try{
      await apiCall('/api/bribe');
      showToast('👮 Cops bribed — clear for 5 minutes.');
      render();
    } catch(e){ /* toast already shown */ }
  }

  function updateBribeUI(){
    const bribeBtn = document.getElementById('bribeBtn');
    const bribeHint = document.getElementById('bribeHint');
    if(!bribeBtn || !bribeHint) return;
    const now = Date.now();
    const activeRemaining = (state.bribeActiveUntil || 0) - now;
    const cooldownRemaining = (state.bribeCooldownUntil || 0) - now;
    const fmtMMSS = ms => {
      const mins = Math.floor(ms / 60000);
      const secs = Math.floor((ms % 60000) / 1000);
      return `${mins}:${secs.toString().padStart(2,'0')}`;
    };
    if(activeRemaining > 0){
      bribeBtn.disabled = true;
      bribeBtn.textContent = `👮 Cops looking away (${fmtMMSS(activeRemaining)})`;
      bribeHint.textContent = `The cops are bribed — no raids for ${fmtMMSS(activeRemaining)}.`;
    } else if(cooldownRemaining > 0){
      bribeBtn.disabled = true;
      bribeBtn.textContent = `👮 On cooldown (${fmtMMSS(cooldownRemaining)})`;
      bribeHint.textContent = `They won't take another bribe for ${fmtMMSS(cooldownRemaining)}.`;
    } else {
      bribeBtn.textContent = `👮 Bribe the Cops — ${fmtMoney(bribeCost())}`;
      bribeBtn.disabled = state.cash < bribeCost();
      bribeHint.textContent = `Keeps raids off your back for 5 minutes · once every hour · £15 per hoe on the roster.`;
    }
  }

  function layLowCost(){
    return Math.max(1, Math.round(totalNetWorth() * 0.10));
  }

  async function layLow(){
    try{
      await apiCall('/api/laylow');
      showToast('🕶️ Off the radar — lying low for 15 minutes.');
      render();
    } catch(e){ /* toast already shown */ }
  }

  function updateLayLowUI(){
    const btn = document.getElementById('layLowBtn');
    const hint = document.getElementById('layLowHint');
    if(!btn || !hint) return;
    const now = Date.now();
    const activeRemaining = (state.layLowUntil || 0) - now;
    const cooldownRemaining = (state.layLowCooldownUntil || 0) - now;
    const fmtMMSS = ms => {
      const mins = Math.floor(ms / 60000);
      const secs = Math.floor((ms % 60000) / 1000);
      return `${mins}:${secs.toString().padStart(2,'0')}`;
    };
    const overlay = document.getElementById('layLowOverlay');
    const badge = document.getElementById('layLowBadge');
    const badgeTime = document.getElementById('layLowBadgeTime');
    if(activeRemaining > 0){
      btn.disabled = true;
      btn.textContent = `🕶️ Lying low (${fmtMMSS(activeRemaining)})`;
      hint.textContent = `You're off the radar — invisible on the leaderboard, city hidden, for ${fmtMMSS(activeRemaining)} more.`;
      if(overlay) overlay.classList.add('active');
      if(badge) badge.classList.add('active');
      if(badgeTime) badgeTime.textContent = fmtMMSS(activeRemaining);
    } else if(cooldownRemaining > 0){
      btn.disabled = true;
      const cdMins = Math.floor(cooldownRemaining / 60000);
      const cdH = Math.floor(cdMins / 60);
      const cdM = cdMins % 60;
      btn.textContent = `🕶️ On cooldown (${cdH}h ${cdM}m)`;
      hint.textContent = `Can't lay low again for ${cdH}h ${cdM}m.`;
      if(overlay) overlay.classList.remove('active');
      if(badge) badge.classList.remove('active');
    } else {
      btn.textContent = `🕶️ Lay Low — ${fmtMoney(layLowCost())}`;
      btn.disabled = state.cash < layLowCost();
      hint.textContent = `Go off the radar for 15 minutes — invisible on the leaderboard as online, city hidden. You can still do everything, including attack · 10% of your net worth · once every 8 hours.`;
      if(overlay) overlay.classList.remove('active');
      if(badge) badge.classList.remove('active');
    }
  }



  function travelCapacity(){
    return (state.cadillacs || 0) * TRAVEL_THUGS_PER_CADILLAC + (state.armoredTrucks || 0) * TRAVEL_THUGS_PER_ARMORED_TRUCK;
  }



  // NOTE: bots (and now other real players) are entirely server-authoritative -
  // every response from the Flask backend already carries a complete, correct
  // `state.bots` array. This used to regenerate a fresh random 19-bot roster
  // whenever `state.bots.length !== BOT_COUNT`, which was harmless back when
  // bots only ever lived in this one player's own state (so the length was
  // always exactly BOT_COUNT) - now that `state.bots` also includes every
  // other real player, the length is never BOT_COUNT, so this fired on every
  // single render and wiped the real shared roster with fake random data.
  // Left as a no-op rather than removed, since it's still called defensively
  // in several render paths.
  function ensureBots(){}

  function botsInCity(cityName){
    return (state.bots || []).filter(b => b.city === cityName);
  }

  function factorySellValue(f){
    f = f || {};
    return (f.medical||0)*FACTORY_SELL_PRICES.medical + (f.gun||0)*FACTORY_SELL_PRICES.gun + (f.car||0)*FACTORY_SELL_PRICES.car
      + (f.drug||0)*FACTORY_SELL_PRICES.drug + (f.explosive||0)*FACTORY_SELL_PRICES.explosive + (f.counterfeit||0)*FACTORY_SELL_PRICES.counterfeit
      + (f.gym||0)*FACTORY_SELL_PRICES.gym;
  }

  function botNetWorth(b){
    return factorySellValue(b.factories) + (b.thugs || 0) * THUG_NET_WORTH_VALUE;
  }

  function botTotalGuns(b){
    return Object.values(b.guns || {}).reduce((a, c) => a + c, 0);
  }

  function botTotalFactories(b){
    return Object.values(b.factories || {}).reduce((a, c) => a + c, 0);
  }

  function crewRosterIds(){
    return new Set(((state.crewRoster && state.crewRoster.members) || []).map(m => m.botId));
  }

  function getPlayerCityRank(){
    ensureBots();
    const playerNW = totalNetWorth();
    const cityBots = botsInCity(state.location);
    const betterBots = cityBots.filter(b => botNetWorth(b) > playerNW).length;
    return betterBots + 1;
  }

  let lastBgCity = null;

  function updateBackgroundForCity(){
    const bgScene = document.querySelector('.bg-scene');
    if(!bgScene) return;
    const city = state.location || 'London';
    if(city === lastBgCity) return; // avoid re-triggering the fade on every render tick
    lastBgCity = city;
    const cityLower = city.toLowerCase();
    const bgImage = `url('./${cityLower}.jpg')`;

    // Trigger fade animation by resetting animation
    bgScene.style.animation = 'none';
    setTimeout(() => {
      bgScene.style.backgroundImage = bgImage;
      bgScene.style.animation = 'bgFade 1s ease-in-out';
    }, 10);
  }

  function getDealerPrice(city, drugId, isSelling){
    const now = Date.now();
    const lastUpdate = state.lastDealerPriceUpdate || 0;
    const minutesPassed = (now - lastUpdate) / (10 * 60 * 1000);

    // Reset prices and bought count every 10 minutes
    if(minutesPassed >= 1){
      state.dealerPrices = {};
      state.dealerBoughtToday = {};
      state.lastDealerPriceUpdate = now;
    }

    const key = `${city}_${drugId}`;
    if(!state.dealerPrices[key]){
      const drug = DOPE_DEALER_DRUGS.find(d => d.id === drugId);
      const variance = 0.80 + Math.random() * 0.4; // 80%-120% variance
      state.dealerPrices[key] = {
        buy: Math.round(drug.baseBuyPrice * variance),
        sell: Math.round(drug.baseSellPrice * variance),
      };
    }
    return isSelling ? state.dealerPrices[key].sell : state.dealerPrices[key].buy;
  }

  async function buyDrugs(drugId, qty){
    try{
      const data = await apiCall('/api/drugs/buy', {drugId, qty});
      showToast(`💊 Bought ${qty}x for ${fmtMoney(data.result.totalCost)}`);
      render(); renderDealer();
    } catch(e){ /* toast already shown */ }
  }

  async function sellDrugs(drugId, qty){
    try{
      const data = await apiCall('/api/drugs/sell', {drugId, qty});
      showToast(`💸 Sold ${qty}x for ${fmtMoney(data.result.totalEarnings)}`);
      render(); renderDealer();
    } catch(e){ /* toast already shown */ }
  }

  function getPlayerGlobalRank(){
    ensureBots();
    const playerNW = totalNetWorth();
    const betterBots = state.bots.filter(b => botNetWorth(b) > playerNW).length;
    return betterBots + 1;
  }

  async function quickBuyMeds(){
    const slider = document.getElementById('hoMedsSlider');
    const qty = slider ? (parseInt(slider.value) || 1) : 1;
    try{
      const data = await apiCall('/api/blackmarket/buy', {key: 'meds', qty});
      showToast(`💊 Bought ${qty}x Safety Kits for ${fmtMoney(data.result.totalCost)}`);
      render();
    } catch(e){ /* toast already shown */ }
  }

  function updateMedsOverlayQty(){
    const slider = document.getElementById('hoMedsSlider');
    const label = document.getElementById('hoMedsQtyLabel');
    const btn = document.getElementById('quickBuyMedsBtn');
    if(!slider || !label || !btn) return;
    const medsItem = BLACKMARKET_ITEMS.find(i => i.key === 'meds');
    const qty = parseInt(slider.value) || 1;
    label.textContent = qty;
    btn.textContent = `Quick Buy Meds — ${fmtMoney(medsItem.price * qty)}`;
    btn.disabled = state.cash < medsItem.price * qty;
  }

  function renderHappinessOverlay(){
    const slider = document.getElementById('hoMedsSlider');
    if(!slider) return;

    const medsItem = BLACKMARKET_ITEMS.find(i => i.key === 'meds');
    const afford = Math.max(1, Math.floor(state.cash / medsItem.price));
    slider.max = afford;
    if(parseInt(slider.value) > afford) slider.value = afford;
    updateMedsOverlayQty();
  }

  const CITY_COORDS = {
    London: {lat:51.5074, lng:-0.1278},
    Bristol: {lat:51.4545, lng:-2.5879},
    Birmingham: {lat:52.4862, lng:-1.8904},
    Manchester: {lat:53.4808, lng:-2.2426},
    Liverpool: {lat:53.4084, lng:-2.9916},
    Leeds: {lat:53.8008, lng:-1.5491},
    Amsterdam: {lat:52.3676, lng:4.9041},
    Dublin: {lat:53.3498, lng:-6.2603},
  };

  let ukMapInstance = null;
  let ukMapMarkers = null;

  function initUkMap(){
    if(ukMapInstance) return;
    const el = document.getElementById('ukMap');
    if(!el) return;
    if(typeof L === 'undefined'){
      if(!el.dataset.fallbackShown){
        el.dataset.fallbackShown = '1';
        el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;text-align:center;padding:20px;">Map couldn\'t load — check your internet connection.</div>';
      }
      return;
    }
    ukMapInstance = L.map(el, {
      scrollWheelZoom: false,
      minZoom: 4,
      maxZoom: 9,
    }).setView([52.6, -0.6], 5);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(ukMapInstance);
    ukMapMarkers = L.layerGroup().addTo(ukMapInstance);
  }

  function travelCost(city){
    return Math.max(TRAVEL_BASE_FEE, Math.round(TRAVEL_COST_PER_THUG * state.thugs));
  }

  function renderLocation(){
    document.getElementById('curLocation').textContent = state.location;
    initUkMap();
    if(ukMapInstance) setTimeout(() => ukMapInstance.invalidateSize(), 0);

    ensureBots();

    const capacity = travelCapacity();
    const shortOnCars = capacity < state.thugs;

    if(ukMapMarkers){
      ukMapMarkers.clearLayers();
      CITIES.forEach(c => {
        const isCurrent = c.name === state.location;
        const cost = travelCost(c);
        const cantAfford = !isCurrent && (state.cash < cost || shortOnCars);
        const coord = CITY_COORDS[c.name];
        const crewCount = botsInCity(c.name).length;
        const costLabel = isCurrent ? 'here' : (shortOnCars ? 'not enough cars' : `${fmtMoney(cost)}${crewCount ? ` · ${crewCount} crew${crewCount === 1 ? '' : 's'}` : ''}`);
        const color = isCurrent ? '#2fe0c0' : (cantAfford ? '#5a5566' : '#ff2f78');

        const marker = L.circleMarker([coord.lat, coord.lng], {
          radius: isCurrent ? 9 : 7,
          color: '#0b0910',
          weight: 1.5,
          fillColor: color,
          fillOpacity: 0.95,
        });
        marker.bindTooltip(
          `<div class="city-pin-label${cantAfford ? ' disabled' : ''}">${c.name}<span class="ccost">${costLabel}</span></div>`,
          {permanent: true, direction: 'top', className: 'city-pin-tooltip', offset: [0, -6]}
        );
        if(!isCurrent && !cantAfford){
          marker.on('click', () => travelTo(c.name));
        }
        marker.addTo(ukMapMarkers);
      });
    }

    const travelHint = document.getElementById('travelHint');
    travelHint.textContent = shortOnCars
      ? `not enough cars to move your crew — need ${state.thugs.toLocaleString()} seats, you've got ${capacity.toLocaleString()} (buy cadillacs/armored trucks in the Black Market)`
      : 'work the block freely';

    const cityGrid = document.getElementById('cityGrid');
    if(cityGrid){
      cityGrid.innerHTML = CITIES.map(c => {
        const isCurrent = c.name === state.location;
        const cost = travelCost(c);
        const cantAfford = !isCurrent && (state.cash < cost || shortOnCars);
        const crewCount = botsInCity(c.name).length;
        const costLabel = isCurrent ? 'current turf' : (shortOnCars ? 'not enough cars' : `${fmtMoney(cost)} plane ticket${state.thugs === 1 ? '' : 's'}`);
        return `
          <button type="button" class="city-card${isCurrent ? ' current' : ''}${cantAfford ? ' disabled' : ''}"
            data-travel-city="${escapeHtml(c.name)}" ${isCurrent || cantAfford ? 'disabled' : ''}>
            <div class="cname">${escapeHtml(c.name)}</div>
            <div class="ccost">${costLabel}</div>
            <div class="cflag">${crewCount ? `${crewCount} crew${crewCount === 1 ? '' : 's'}` : 'quiet'}</div>
          </button>`;
      }).join('');
      cityGrid.querySelectorAll('[data-travel-city]:not(:disabled)').forEach(btn => {
        btn.addEventListener('click', () => travelTo(btn.dataset.travelCity));
      });
    }
  }

  const BOT_ARCHETYPE_INFO = {
    hustler: {icon: '💃', label: 'Hustler', desc: 'Invests hard in hoes'},
    enforcer: {icon: '🥊', label: 'Enforcer', desc: 'Invests hard in muscle'},
    mogul: {icon: '🏦', label: 'Mogul', desc: 'Ploughs cash into factories'},
    shark: {icon: '🦈', label: 'Shark', desc: 'Preys on other crews in town'},
  };

  // Legacy emoji emblems - no longer offered in the picker (looked like
  // garbage next to the real image emblems below). Kept only so old saved
  // values still render as *something* instead of going blank.
  const LEGACY_EMOJI_EMBLEMS = ['🐍', '🦂', '🐺', '💀', '🔥', '👑', '🗡️', '🦅', '🐉', '⚡', '🎩', '♠️'];
  // Image-based emblems - id -> file under ./crew_emblems/.
  const IMAGE_EMBLEMS = {
    the_pride: 'crew_emblems/the_pride.gif',
    the_forge: 'crew_emblems/the_forge.gif',
    the_serpents_fang: 'crew_emblems/the_serpents_fang.gif',
    the_royal_dead: 'crew_emblems/the_royal_dead.gif',
    the_stormbringers: 'crew_emblems/the_stormbringers.gif',
    the_stormbringers_2: 'crew_emblems/the_stormbringers_2.gif',
    the_watchers: 'crew_emblems/the_watchers.gif',
    the_nightfall_crew: 'crew_emblems/the_nightfall_crew.gif',
    the_ironclad: 'crew_emblems/the_ironclad.gif',
    the_reborn: 'crew_emblems/the_reborn.gif',
    the_riptide: 'crew_emblems/the_riptide.gif',
    the_contagion: 'crew_emblems/the_contagion.gif',
    the_pathfinders: 'crew_emblems/the_pathfinders.gif',
    the_maulers: 'crew_emblems/the_maulers.gif',
    the_breakers: 'crew_emblems/the_breakers.gif',
    the_stargazers: 'crew_emblems/the_stargazers.gif',
    the_wyverns: 'crew_emblems/the_wyverns.gif',
    the_rustlers: 'crew_emblems/the_rustlers.gif',
    the_metropolitans: 'crew_emblems/the_metropolitans.gif',
    the_chroniclers: 'crew_emblems/the_chroniclers.gif',
    the_lone_wolves: 'crew_emblems/the_lone_wolves.gif',
    the_squad: 'crew_emblems/the_squad.webp',
    the_crescent: 'crew_emblems/the_crescent.webp',
    the_crossfire: 'crew_emblems/the_crossfire.webp',
    the_open_hand: 'crew_emblems/the_open_hand.gif',
    the_shadow_circle: 'crew_emblems/the_shadow_circle.webp',
    the_ok_hand: 'crew_emblems/the_ok_hand.gif',
    the_balance: 'crew_emblems/the_balance.gif',
    the_rage: 'crew_emblems/the_rage.webp',
    the_quick_escape: 'crew_emblems/the_quick_escape.webp',
    the_gold_balance: 'crew_emblems/the_gold_balance.gif',
    the_neon_dancer: 'crew_emblems/the_neon_dancer.webp',
    the_statement: 'crew_emblems/the_statement.webp',
    the_criminal: 'crew_emblems/the_criminal.webp',
    the_pointed_gun: 'crew_emblems/the_pointed_gun.webp',
    the_shadow_gunman: 'crew_emblems/the_shadow_gunman.webp',
    the_mac10: 'crew_emblems/the_mac10.webp',
    the_anime_cube: 'crew_emblems/the_anime_cube.webp',
    the_siren: 'crew_emblems/the_siren.webp',
    the_run_and_gun: 'crew_emblems/the_run_and_gun.webp',
    the_partners_in_crime: 'crew_emblems/the_partners_in_crime.webp',
  };
  const ALL_EMBLEM_IDS = () => Object.keys(IMAGE_EMBLEMS);

  // Small inline glyph for names/rows (leaderboard, profile, etc). Sized a
  // bit bigger than 1em so it actually reads on the leaderboard rows.
  function emblemInlineHtml(id){
    if(!id) return '';
    if(IMAGE_EMBLEMS[id]) return `<img src="${IMAGE_EMBLEMS[id]}" alt="" style="height:1.7em; width:1.7em; object-fit:contain; vertical-align:-0.5em;">`;
    if(LEGACY_EMOJI_EMBLEMS.includes(id)) return `<span style="font-size:1.4em;">${escapeHtml(id)}</span>`;
    return escapeHtml(id);
  }

  function renderCrewEmblemPicker(){
    const picker = document.getElementById('crewEmblemPicker');
    if(!picker) return;

    const isMember = !!state.crewLeaderUserId;
    const leaderName = document.getElementById('crewLeaderName');
    if(leaderName) leaderName.textContent = isMember ? (state.crewLeaderName || '—') : (state.name || 'You');

    if(!state.gang){
      picker.innerHTML = '<div class="hint">Set a crew name above first — that makes you the crew leader and unlocks emblem selection.</div>';
      return;
    }

    if(isMember){
      picker.innerHTML = `<div class="hint">Only ${escapeHtml(state.crewLeaderName || 'the crew leader')} can set the emblem — you joined this crew as a member.</div>`;
      return;
    }

    const botEmblems = state.botCrewEmblems || {};
    const takenBy = {};
    Object.entries(botEmblems).forEach(([crew, e]) => { takenBy[e] = crew; });

    const emblemLabel = id => IMAGE_EMBLEMS[id]
      ? id.replace(/^the_/, 'The ').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
      : '';

    picker.innerHTML = ALL_EMBLEM_IDS().map(id => {
      const mine = state.crewEmblem === id;
      const taken = takenBy[id] && !mine;
      const inner = IMAGE_EMBLEMS[id]
        ? `<img src="${IMAGE_EMBLEMS[id]}" alt="" style="width:100%; height:100%; object-fit:contain;">`
        : id;
      const label = taken ? `Taken by ${takenBy[id]}` : emblemLabel(id);
      return `<button class="crew-emblem-btn" data-emblem="${id}" ${taken ? 'disabled' : ''}
        title="${escapeHtml(label)}"
        style="font-size:1.6rem; width:48px; height:48px; border-radius:8px; background:var(--bg-2); padding:4px;
        border:2px solid ${mine ? 'var(--gold)' : 'var(--panel-line)'};
        cursor:${taken ? 'not-allowed' : 'pointer'}; opacity:${taken ? '0.3' : '1'};">${inner}</button>`;
    }).join('');
    picker.querySelectorAll('[data-emblem]:not(:disabled)').forEach(btn => {
      btn.addEventListener('click', () => setCrewEmblem(btn.dataset.emblem));
    });
  }

  async function setCrewEmblem(emblem){
    try{
      await apiCall('/api/crew/emblem', {emblem});
      render(); renderCrewEmblemPicker();
    } catch(e){ /* toast already shown */ }
  }

  let lbActiveTab = 'global';
  // Rank-movement arrows compare against a baseline snapshot that only
  // refreshes every 5 minutes (not on every render/poll), so an arrow stays
  // put instead of flickering in and out as the leaderboard redraws.
  const lbBaselineRanks = {global: {}, city: {}};
  const lbBaselineTime = {global: 0, city: 0};
  const LB_ARROW_REFRESH_MS = 5 * 60 * 1000;

  function setLbTab(tab){
    lbActiveTab = tab;
    document.querySelectorAll('.lb-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.lbtab === tab);
    });
    renderLeaderboard();
  }

  function renderLeaderboard(){
    ensureBots();
    const header = document.getElementById('lbHeader');
    const list = document.getElementById('lbList');
    if(!list || !header) return;

    if(lbActiveTab === 'crew'){
      renderCrewGroupLeaderboard(header, list);
      return;
    }

    header.classList.remove('lb-crewview');
    list.classList.remove('lb-crewview');
    header.innerHTML = `<div>#</div><div>Player</div><div>Crew</div><div>City</div><div>Hoes</div><div>Thugs</div><div>Cars</div><div style="text-align:right;">Net Worth</div>`;

    const playerNW = totalNetWorth();
    const minAttackNW = playerNW * 0.5;
    const maxAttackNW = playerNW * 2;

    let bots = state.bots;
    if(lbActiveTab === 'city'){
      bots = bots.filter(b => b.city === state.location);
    }

    const rosterIds = crewRosterIds();
    const rows = bots.map(b => {
      const inYourCrew = rosterIds.has(b.id);
      const botNW = botNetWorth(b);
      const isInRange = botNW >= minAttackNW && botNW <= maxAttackNW;
      return {
        isYou: false,
        isHuman: !!b.isHuman,
        isOnline: !!b.isOnline,
        isDon: !!b.isHuman && (b.rankLevel || 1) >= 13,
        botId: b.id,
        name: b.boss,
        // Recruited bots fly your crew's colors, not their old street gang
        gang: inYourCrew ? (state.gang || '') : (b.gang || ''),
        emblem: inYourCrew ? ((state.crewRoster && state.crewRoster.emblem) || '') : ((state.botCrewEmblems || {})[b.gang] || ''),
        inYourCrew: !!inYourCrew,
        city: b.city,
        hoes: b.hoes,
        thugs: b.thugs,
        cars: b.cadillacs || 0,
        netWorth: botNW,
        isInRange: isInRange,
        sameCity: b.city === state.location,
      };
    });
    // You're always "in" your own city, so you belong on both tabs
    rows.push({
      isYou: true,
      isDon: (state.rankInfo?.level || 1) >= 13,
      botId: null,
      name: state.name || 'Big Boss',
      gang: state.gang || '',
      emblem: (state.crewRoster && state.crewRoster.emblem) || '',
      city: state.location,
      hoes: state.hoes,
      thugs: state.thugs,
      cars: state.cadillacs || 0,
      netWorth: playerNW,
      isInRange: false,
    });
    rows.sort((a,b) => b.netWorth - a.netWorth);

    const baseline = lbBaselineRanks[lbActiveTab];
    rows.forEach((r, i) => {
      const key = r.isYou ? 'you' : r.botId;
      const rank = i + 1;
      const baseRank = baseline[key];
      r.rankArrow = (baseRank !== undefined && baseRank > rank)
        ? '<span style="color:var(--teal); font-weight:700;" title="Climbed">▲</span>'
        : (baseRank !== undefined && baseRank < rank)
          ? '<span style="color:var(--danger); font-weight:700;" title="Dropped">▼</span>'
          : '<span style="color:var(--teal); font-weight:700;" title="No change">–</span>';
    });
    // Only move the comparison baseline forward once the 5-minute window's
    // up, so arrows hold steady across every render/poll in between.
    const nowTs = Date.now();
    if(nowTs - lbBaselineTime[lbActiveTab] >= LB_ARROW_REFRESH_MS){
      const freshBaseline = {};
      rows.forEach((r, i) => { freshBaseline[r.isYou ? 'you' : r.botId] = i + 1; });
      lbBaselineRanks[lbActiveTab] = freshBaseline;
      lbBaselineTime[lbActiveTab] = nowTs;
    }

    const rankTier = i => i === 0 ? 'lb-gold' : i === 1 ? 'lb-silver' : i === 2 ? 'lb-bronze' : '';
    const rankMedal = i => i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '';
    const crosshairHtml = r => {
      if(r.isYou || r.inYourCrew || !r.isInRange) return '<span class="lb-crosshair-slot"></span>';
      return r.sameCity
        ? `<span class="lb-crosshair-slot"><button class="lb-quick-attack-btn" data-quick-attack-id="${r.botId}" title="Quick attack — send all thugs" style="background:none; border:none; cursor:pointer; font-size:1.2rem; line-height:1; padding:2px 4px; color:var(--red); font-weight:700;">⌖</button></span>`
        : `<span class="lb-crosshair-slot"><button class="lb-quick-attack-btn" data-travel-hint-city="${escapeHtml(r.city)}" data-travel-hint-name="${escapeHtml(r.name)}" title="In attack range — travel to ${escapeHtml(r.city)} to hit them" style="background:none; border:none; cursor:pointer; font-size:1.2rem; line-height:1; padding:2px 4px; color:var(--text-dim); font-weight:700;">⌖</button></span>`;
    };
    list.innerHTML = rows.map((r,i) => `
      <div class="lb-row ${r.isYou ? 'lb-you' : (r.inYourCrew ? 'lb-crewmate' : '')}">
        <div class="lb-rank ${rankTier(i)}">${rankMedal(i)}${ordinal(i + 1)} ${r.rankArrow}</div>
        <div class="lb-name">
          ${crosshairHtml(r)}
          <span>${r.isDon ? '<span title="THE DON — reached the top of the game">👑</span> ' : ''}${r.isHuman && !r.isYou ? `<span data-profile-id="${r.botId}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(r.name)}</span>` : escapeHtml(r.name)}${r.isHuman ? ` <span class="lb-presence-dot ${r.isOnline ? 'online' : 'offline'}" title="Real player — ${r.isOnline ? 'online now' : 'offline'}"></span>` : ''}</span>
          ${!r.isYou ? `<button class="dm-btn" data-dm-id="${r.botId}" style="margin-left:8px; background:none; border:none; cursor:pointer; font-size:1.1rem; padding:2px 4px;">✉️</button>` : ''}
        </div>
        <div class="lb-gang">${r.gang ? `${r.emblem ? emblemInlineHtml(r.emblem) + ' ' : ''}${escapeHtml(r.gang)}` : '—'}</div>
        <div class="lb-city">${escapeHtml(r.city)}</div>
        <div class="lb-stat"><img src="./hoes-icon.png" alt="Hoes" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.hoes}</div>
        <div class="lb-stat"><img src="./thug-icon.jpg" alt="Thugs" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.thugs}</div>
        <div class="lb-stat"><img src="./cadillac-icon.png" alt="Cars" style="height:1em; width:1.6em; object-fit:contain; vertical-align:-2px;"> ${Math.floor(r.cars)}</div>
        <div class="lb-nw">${fmtMoney(r.netWorth)}</div>
      </div>
    `).join('');

    // Wire up DM buttons
    list.querySelectorAll('[data-dm-id]').forEach(btn => {
      btn.addEventListener('click', () => openDMModal(parseInt(btn.dataset.dmId)));
    });

    // Wire up quick-attack (target icon only renders when in range and in your city)
    list.querySelectorAll('[data-quick-attack-id]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        fightBot(parseInt(btn.dataset.quickAttackId));
      });
    });

    // Grey crosshair = in attack range but a different city - not clickable to attack yet
    list.querySelectorAll('[data-travel-hint-city]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        showToast(`✈️ ${btn.dataset.travelHintName} is in range but in ${btn.dataset.travelHintCity} — travel there to attack`);
      });
    });

    // Wire up clickable names (real players only - opens their profile)
    list.querySelectorAll('[data-profile-id]').forEach(el => {
      el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
    });
  }

  function renderCrewGroupLeaderboard(header, list){
    header.classList.add('lb-crewview');
    list.classList.add('lb-crewview');
    header.innerHTML = `<div>#</div><div>Crew</div><div>Members</div><div>Hoes</div><div>Thugs</div><div>Cars</div><div style="text-align:right;">Net Worth</div>`;

    // A bot can only belong to one crew at a time - once you've recruited
    // them into your own crew, they no longer count toward their old
    // street gang's totals below. The full roster (server-computed, since
    // only the leader's own state tracks it) is what tells us who's taken.
    const roster = (state.crewRoster && state.crewRoster.members) || [];
    const recruitedIds = new Set(roster.map(m => m.botId));

    const groups = {};
    state.bots.forEach(b => {
      if(recruitedIds.has(b.id)) return;
      const g = b.gang || 'Unaffiliated';
      if(!groups[g]) groups[g] = {name: g, emblem: (state.botCrewEmblems||{})[g] || '', members: 0, hoes: 0, thugs: 0, cars: 0, netWorth: 0, isYours: false};
      groups[g].members += 1;
      groups[g].hoes += b.hoes;
      groups[g].thugs += b.thugs;
      groups[g].cars += (b.cadillacs || 0);
      groups[g].netWorth += botNetWorth(b);
    });

    // Your own personal crew (Crew page > Crew Name + recruited members) is a
    // separate system from the bots' street-gang affiliations above - add it
    // in as its own competing entry so it shows up here too, whether you're
    // the leader or just a member of it.
    if(state.gang && roster.length){
      const mine = {name: state.gang, emblem: (state.crewRoster && state.crewRoster.emblem) || '', members: 0, hoes: 0, thugs: 0, cars: 0, netWorth: 0, isYours: true};
      roster.forEach(m => {
        mine.members += 1;
        // Use live local numbers for your own row so it doesn't lag a
        // server round-trip behind whatever you just did.
        mine.hoes += m.isYou ? state.hoes : m.hoes;
        mine.thugs += m.isYou ? state.thugs : m.thugs;
        mine.cars += m.isYou ? (state.cadillacs || 0) : m.cars;
        mine.netWorth += m.isYou ? totalNetWorth() : m.netWorth;
      });
      groups[state.gang] = mine;
    }

    const rows = Object.values(groups).sort((a,b) => b.netWorth - a.netWorth);

    const rankTier = i => i === 0 ? 'lb-gold' : i === 1 ? 'lb-silver' : i === 2 ? 'lb-bronze' : '';
    const rankMedal = i => i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '';
    list.innerHTML = rows.map((r,i) => `
      <div class="lb-row lb-crewview ${r.isYours ? 'lb-you' : ''}">
        <div class="lb-rank ${rankTier(i)}">${rankMedal(i)}${ordinal(i + 1)}</div>
        <div class="lb-name">${r.emblem ? emblemInlineHtml(r.emblem) + ' ' : ''}${escapeHtml(r.name)}${r.isYours ? ' <span style="color:var(--teal); font-size:0.75rem;">(you)</span>' : ''}</div>
        <div class="lb-stat">${r.members}</div>
        <div class="lb-stat"><img src="./hoes-icon.png" alt="Hoes" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.hoes}</div>
        <div class="lb-stat"><img src="./thug-icon.jpg" alt="Thugs" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.thugs}</div>
        <div class="lb-stat"><img src="./cadillac-icon.png" alt="Cars" style="height:1em; width:1.6em; object-fit:contain; vertical-align:-2px;"> ${Math.floor(r.cars)}</div>
        <div class="lb-nw">${fmtMoney(r.netWorth)}</div>
      </div>
    `).join('');
  }

  async function travelTo(name){
    try{
      const data = await apiCall('/api/travel', {city: name});
      showToast(`Traveled to ${name} for ${fmtMoney(data.result.cost)}.`);
      render(); renderLocation();
    } catch(e){ /* toast already shown */ }
  }

  async function fightBot(botId){
    try{
      const data = await apiCall('/api/attack', {botId});
      const r = data.result;
      showGunfireAnimation();
      playAttackAlert();
      showAttackResultModal(r);
      render(); renderLocation(); renderAttacks();
    } catch(e){ /* toast already shown */ }
  }

  function showAttackResultModal(r){
    const modal = document.getElementById('attackResultModal');
    const box = document.getElementById('attackResultBox');
    const icon = document.getElementById('attackResultIcon');
    const title = document.getElementById('attackResultTitle');
    const sub = document.getElementById('attackResultSub');
    const content = document.getElementById('attackResultContent');
    if(!modal) return;

    if(r.won){
      box.style.borderColor = 'var(--teal)';
      box.style.boxShadow = '0 0 30px rgba(47,224,192,0.4)';
      icon.textContent = '🏆';
      title.textContent = 'VICTORY';
      title.style.color = 'var(--teal)';
      sub.innerHTML = r.yourThugsLost > 0
        ? `You ran <b>${escapeHtml(r.boss)}</b> and his crew <b>"${escapeHtml(r.gang)}"</b> off the block — but ${r.yourThugsLost} of your thugs fired back and died taking them down.`
        : `You ran <b>${escapeHtml(r.boss)}</b> and his crew <b>"${escapeHtml(r.gang)}"</b> off the block.`;
      content.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px; font-family:'IBM Plex Mono',monospace;">
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">Cash looted</span>
            <span style="color:var(--gold); font-weight:700;">+${fmtMoney(r.cashWon)}</span>
          </div>
          ${r.bountyWon ? `<div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px; border:1px solid var(--gold);">
            <span style="color:var(--text-dim);">🎯 Bounty collected</span>
            <span style="color:var(--gold); font-weight:700;">+${fmtMoney(r.bountyWon)}</span>
          </div>` : ''}
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">Their thugs wiped</span>
            <span style="color:var(--teal); font-weight:700;">${r.thugsWiped}</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">Hospitalized (back in 2 min)</span>
            <span style="font-weight:700;">${r.thugsHospitalized}</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px; border:1px solid var(--danger);">
            <span style="color:var(--text-dim);">Your thugs lost</span>
            <span style="color:var(--danger); font-weight:700;">-${r.yourThugsLost}</span>
          </div>
        </div>`;
    } else {
      box.style.borderColor = 'var(--danger)';
      box.style.boxShadow = '0 0 30px rgba(255,77,77,0.4)';
      icon.textContent = '💥';
      title.textContent = 'YOU GOT HIT';
      title.style.color = 'var(--danger)';
      sub.innerHTML = `Attacked by <b>${escapeHtml(r.boss)}</b> of <b>"${escapeHtml(r.gang)}"</b> — here's what they took:`;
      content.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px; font-family:'IBM Plex Mono',monospace;">
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px; border:1px solid var(--danger);">
            <span style="color:var(--text-dim);">Cash taken</span>
            <span style="color:var(--danger); font-weight:700;">-${fmtMoney(r.cashLost)}</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px; border:1px solid var(--danger);">
            <span style="color:var(--text-dim);">Thugs taken out</span>
            <span style="color:var(--danger); font-weight:700;">-${r.thugsLost}</span>
          </div>
        </div>`;
    }

    modal.classList.remove('hidden');
  }

  const FACTORY_TYPE_LABELS = {medical: 'Medical', gun: 'Gun', car: 'Car', drug: 'Drug', explosive: 'Explosive', counterfeit: 'Counterfeit', gym: 'Gym', warehouse: 'Warehouse'};
  const FACTORY_EMOJI = {medical: '🏥', gun: '🏭', car: '🏗️', drug: '❄️', explosive: '💣', counterfeit: '💰', gym: '🏋️', warehouse: '📦'};

  async function bombFactory(targetId, type){
    try{
      const data = await apiCall('/api/attack/bomb', 'POST', {targetId, type});
      showExplosionAnimation();
      playBombSound();
      showBombResultModal(data.result);
      render(); renderLocation(); renderAttacks();
    } catch(e){ /* toast already shown */ }
  }

  function showBombResultModal(r){
    const modal = document.getElementById('bombResultModal');
    const box = document.getElementById('bombResultBox');
    const icon = document.getElementById('bombResultIcon');
    const title = document.getElementById('bombResultTitle');
    const sub = document.getElementById('bombResultSub');
    const content = document.getElementById('bombResultContent');
    if(!modal) return;

    const emoji = FACTORY_EMOJI[r.target] || '💣';
    const label = FACTORY_TYPE_LABELS[r.target] || r.target;
    icon.textContent = emoji;

    if(r.destroyed <= 0){
      box.style.borderColor = 'var(--panel-line)';
      box.style.boxShadow = 'none';
      title.textContent = 'NOTHING TO HIT';
      title.style.color = 'var(--text-dim)';
      sub.innerHTML = `Your thugs went in after <b>${escapeHtml(r.boss)}</b>'s ${label} factories, but they don't own any.`;
      content.innerHTML = `
        <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
          <span style="color:var(--text-dim);">Turns spent for nothing</span>
          <span style="font-weight:700;">${BOMB_TURN_COST}</span>
        </div>`;
    } else {
      box.style.borderColor = 'var(--gold)';
      box.style.boxShadow = '0 0 30px rgba(240,196,25,0.4)';
      title.textContent = r.wipedOut ? 'WIPED OUT' : 'FACTORIES DESTROYED';
      title.style.color = 'var(--gold)';
      sub.innerHTML = r.wipedOut
        ? `You wiped out every ${label} factory <b>${escapeHtml(r.boss)}</b> owned.`
        : `You hit <b>${escapeHtml(r.boss)}</b>'s ${label} factories.`;
      content.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px; font-family:'IBM Plex Mono',monospace;">
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">${emoji} ${label} factories destroyed</span>
            <span style="color:var(--gold); font-weight:700;">${r.destroyed}</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">💣 Bombs used</span>
            <span style="font-weight:700;">${r.bombsSpent.toLocaleString('en-GB')}</span>
          </div>
          <div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px; border:1px solid var(--gold);">
            <span style="color:var(--text-dim);">Net worth destroyed</span>
            <span style="color:var(--gold); font-weight:700;">${fmtMoney(r.networthDestroyed)}</span>
          </div>
          ${r.bombsDestroyed ? `<div style="display:flex; justify-content:space-between; padding:10px; background:var(--bg-2); border-radius:6px;">
            <span style="color:var(--text-dim);">🔥 Their bomb stockpile torched</span>
            <span style="font-weight:700;">${r.bombsDestroyed.toLocaleString('en-GB')}</span>
          </div>` : ''}
        </div>`;
    }

    modal.classList.remove('hidden');
  }

  // Must match STEAL_CARS_THUGS_PER_CAR / STEAL_CARS_TURN_COST in game_engine.py.


  async function stealCars(botId, carType, qty){
    try{
      const data = await apiCall('/api/stealcars', {botId, carType, qty});
      if(data.result.stolen <= 0){
        showToast(`🚗 Your thugs raided ${data.result.boss}'s garage but found 0 ${CAR_TYPE_LABELS[data.result.target]}s to take.`);
      } else {
        const verb = data.result.wipedOut ? `Stole every` : `Stole ${data.result.stolen} of`;
        showToast(`🚗 ${verb} ${CAR_TYPE_LABELS[data.result.target]} ${data.result.boss} owned!`);
      }
      render(); renderLocation(); renderAttacks();
    } catch(e){ /* toast already shown */ }
  }

  const GUN_LABELS = {pistol9mm: '9mm', shotgun12gauge: 'Shotgun', ak47: 'AK-47', m249: 'M249'};

  function renderInformer(){
    ensureBots();
    const select = document.getElementById('informerTargetSelect');
    if(!select) return;
    const targets = (state.bots || []).slice().sort((a,b) => botNetWorth(b) - botNetWorth(a));
    const prevValue = select.value;
    select.innerHTML = targets.map(b =>
      `<option value="${b.id}">${escapeHtml(b.boss)}${b.isHuman ? ' 🧑' : ''} — "${escapeHtml(b.gang || 'Unaffiliated')}" (${b.city})</option>`
    ).join('');
    if(prevValue && targets.find(b => String(b.id) === prevValue)) select.value = prevValue;
    updateInformerCostPreview();
  }

  function updateInformerCostPreview(){
    const select = document.getElementById('informerTargetSelect');
    const preview = document.getElementById('informerCostPreview');
    const buyBtn = document.getElementById('informerBuyBtn');
    if(!select || !preview) return;
    const target = (state.bots || []).find(b => String(b.id) === select.value);
    if(!target){
      preview.textContent = 'No targets available.';
      if(buyBtn) buyBtn.disabled = true;
      return;
    }
    const cost = Math.max(1, Math.round(botNetWorth(target) * INFORMER_COST_PCT));
    preview.textContent = `Cost to expose ${target.boss}: ${fmtMoney(cost)} (${Math.round(INFORMER_COST_PCT*100)}% of their known net worth)`;
    if(buyBtn) buyBtn.disabled = (state.cash || 0) < cost;
  }

  async function buyInformerReport(){
    const select = document.getElementById('informerTargetSelect');
    if(!select || !select.value) return;
    try{
      const data = await apiCall('/api/informer', {targetId: parseInt(select.value)});
      showInformerReport(data.result);
      showToast(`🕵️ Got the lowdown on ${data.result.boss} for ${fmtMoney(data.result.cost)}.`);
      render(); renderInformer();
    } catch(e){ /* toast already shown */ }
  }

  function showInformerReport(r){
    const panel = document.getElementById('informerReportPanel');
    const body = document.getElementById('informerReportBody');
    if(!panel || !body) return;
    const gunLines = Object.entries(r.guns || {}).map(([k,v]) => `${GUN_LABELS[k]||k}: ${v}`).join(' · ');
    const factoryLines = Object.entries(r.factories || {}).map(([k,v]) => `${FACTORY_TYPE_LABELS[k]||k}: ${v}`).join(' · ');
    body.innerHTML = `
      <div style="font-size:1.1rem; font-weight:700; margin-bottom:4px;">${escapeHtml(r.boss)}${r.gang ? ` — "${escapeHtml(r.gang)}"` : ''}</div>
      <div style="color:var(--text-dim); font-size:0.85rem; margin-bottom:12px;">${escapeHtml(r.city || '')} · Net Worth: ${fmtMoney(r.netWorth)} · You paid: ${fmtMoney(r.cost)}</div>
      <div class="bot-stats-row" style="margin-bottom:12px;">
        <span><img src="./cash-icon.jpg" alt="Cash" style="height:1em; width:1em; object-fit:cover; border-radius:50%; vertical-align:-2px;"> ${fmtMoney(r.cash)} cash</span>
        ${r.hoeCash !== undefined ? `<span>💵 ${fmtMoney(r.hoeCash)} hoe earnings</span>` : ''}
        <span><img src="./thug-icon.jpg" alt="Thugs" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.thugs} thugs</span>
        <span><img src="./hoes-icon.png" alt="Hoes" style="height:1em; width:1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-2px;"> ${r.hoes} hoes</span>
        <span>🚗 ${Math.floor(r.cadillacs||0)} cadillacs</span>
        <span>🛡️ ${Math.floor(r.armoredTrucks||0)} trucks</span>
        ${r.bombs !== undefined ? `<span>💣 ${Math.floor(r.bombs)} bombs</span>` : ''}
      </div>
      <div style="font-size:0.85rem; margin-bottom:6px;"><b>Guns:</b> ${gunLines || 'none'}</div>
      <div style="font-size:0.85rem;"><b>Factories:</b> ${factoryLines || 'none'}</div>
    `;
    panel.style.display = 'block';
  }

  function myUserId(){
    return (state.selfProfileId || 0) - 1000000;
  }

  function renderBounties(){
    ensureBots();
    const select = document.getElementById('bountyTargetSelect');
    if(!select) return;
    const targets = (state.bots || []).slice().sort((a,b) => botNetWorth(b) - botNetWorth(a));
    const prevValue = select.value;
    select.innerHTML = targets.map(b =>
      `<option value="${b.id}" data-name="${escapeHtml(b.boss)}">${escapeHtml(b.boss)}${b.isHuman ? ' 🧑' : ''} — "${escapeHtml(b.gang || 'Unaffiliated')}" (${b.city})</option>`
    ).join('');
    if(prevValue && targets.find(b => String(b.id) === prevValue)) select.value = prevValue;

    const list = document.getElementById('bountiesList');
    if(!list) return;
    const bounties = (state.bounties || []).slice().sort((a,b) => b.amount - a.amount);
    const myId = myUserId();
    if(bounties.length === 0){
      list.innerHTML = '<div class="hint">No active bounties yet. Be the first to put one up.</div>';
      return;
    }
    list.innerHTML = bounties.map(b => {
      const targetBot = (state.bots || []).find(t => t.id === b.targetId);
      const defenseless = targetBot && targetBot.thugs === 0;
      const isMine = b.posterId === myId;
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:12px; background:var(--bg-2); border-radius:8px; border:1px solid var(--panel-line);">
          <div>
            <div style="font-weight:700;">${escapeHtml(b.targetName)}${defenseless ? ' <span style="color:var(--danger);">(defenseless right now!)</span>' : ''}</div>
            <div style="font-size:0.8rem; color:var(--text-dim);">Posted by ${escapeHtml(b.posterName)}${isMine ? ' (you)' : ''}</div>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <div style="font-weight:700; color:var(--gold);">${fmtMoney(b.amount)}</div>
            ${isMine ? `<button class="cta cta-sm cta-red" data-cancel-bounty="${b.id}">Cancel</button>` : ''}
          </div>
        </div>`;
    }).join('');
    list.querySelectorAll('[data-cancel-bounty]').forEach(btn => {
      btn.addEventListener('click', () => cancelBounty(parseInt(btn.dataset.cancelBounty)));
    });
  }

  async function postBounty(){
    const select = document.getElementById('bountyTargetSelect');
    const input = document.getElementById('bountyAmountInput');
    if(!select || !select.value) return;
    const amount = parseInt(input.value, 10);
    if(!amount || amount < 1){ showToast('Enter a valid bounty amount'); return; }
    const opt = select.options[select.selectedIndex];
    const targetName = opt ? opt.dataset.name : 'Unknown';
    try{
      const data = await apiCall('/api/bounty/place', {targetId: parseInt(select.value), targetName, amount});
      showToast(`🎯 Posted a ${fmtMoney(data.result.amount)} bounty on ${data.result.targetName}!`);
      render(); renderBounties();
    } catch(e){ /* toast already shown */ }
  }

  async function cancelBounty(bountyId){
    try{
      const data = await apiCall('/api/bounty/cancel', {bountyId});
      showToast(`Pulled your bounty — refunded ${fmtMoney(data.result.amount)}.`);
      render(); renderBounties();
    } catch(e){ /* toast already shown */ }
  }


  // Must match ACHIEVEMENT_MOB_DOLLARS_MIN/DIVISOR in game_engine.py.
  function achievementMobDollars(xp){
    return Math.max(5, Math.floor(xp / 10));
  }

  // Must match RANK_UP_CASH_REWARDS / RANKS in game_engine.py.


  function renderAchievements(){
    const earned = new Set(state.achievements || []);
    const grid = document.getElementById('achievementsGrid');
    document.getElementById('achievementsSubtitle').textContent = `${earned.size} / ${ACHIEVEMENTS.length} badges earned — they show up on your profile.`;
    grid.innerHTML = ACHIEVEMENTS.map(a => {
      const got = earned.has(a.id);
      const mobDollars = achievementMobDollars(a.xp);
      const art = a.img
        ? `<img src="${a.img}" alt="${escapeHtml(a.name)}" style="width:72px; height:72px; object-fit:contain; margin-bottom:6px; filter:${got ? 'none' : 'grayscale(1)'};">`
        : `<div style="font-size:2rem; margin-bottom:6px; filter:${got ? 'none' : 'grayscale(1)'};">${a.emoji}</div>`;
      return `
        <div style="border:1px solid ${got ? 'var(--gold)' : 'var(--panel-line)'}; border-radius:10px; padding:14px; background:${got ? 'rgba(255,200,0,0.08)' : 'var(--bg-2)'}; opacity:${got ? '1' : '0.55'}; text-align:center;">
          ${art}
          <div style="font-weight:700; margin-bottom:4px;">${escapeHtml(a.name)}</div>
          <div style="font-size:0.78rem; color:var(--text-dim); margin-bottom:6px;">${escapeHtml(a.desc)}</div>
          <div style="font-size:0.72rem; color:var(--gold);">${got ? `✅ Earned +${a.xp} XP` : `🔒 +${a.xp} XP`}</div>
          <div style="font-size:0.72rem; color:var(--gold); margin-top:2px;">${got ? '✅' : '🔒'} +${mobDollars} 🪙 Mob Dollars</div>
        </div>
      `;
    }).join('');
    renderRankRewards();
    renderHallOfFame();
  }

  function renderRankRewards(){
    const grid = document.getElementById('rankRewardsGrid');
    if(!grid) return;
    const claimed = new Set(state.rankRewardsClaimed || []);
    const myLevel = state.rankInfo?.level || 1;
    grid.innerHTML = Object.entries(RANK_UP_CASH_REWARDS).map(([levelStr, reward]) => {
      const level = parseInt(levelStr, 10);
      const rankName = RANK_NAMES[level] || `Rank ${level}`;
      const got = claimed.has(level) || myLevel > level;
      const isFinal = level === 8;
      return `
        <div style="border:1px solid ${got ? 'var(--gold)' : 'var(--panel-line)'}; border-radius:10px; padding:14px; background:${got ? 'rgba(255,200,0,0.08)' : 'var(--bg-2)'}; opacity:${got ? '1' : '0.55'}; text-align:center;">
          <div style="font-size:2rem; margin-bottom:6px;">${isFinal ? '👑' : '🎖️'}</div>
          <div style="font-weight:700; margin-bottom:4px;">${escapeHtml(rankName)}${isFinal ? ' (Endgame)' : ''}</div>
          <div style="font-size:0.78rem; color:var(--text-dim); margin-bottom:6px;">Reach Rank ${level}</div>
          <div style="font-size:0.72rem; color:var(--gold);">${got ? `✅ Collected £${reward.toLocaleString()}` : `🔒 £${reward.toLocaleString()} prize`}</div>
        </div>
      `;
    }).join('');
  }

  function renderHallOfFame(){
    const container = document.getElementById('hofLeaderboards');
    const recordEl = document.getElementById('hofRecord');
    if(!container || !recordEl) return;

    const rec = (state.worldRecords && state.worldRecords.biggestHomeInvasion) || null;
    recordEl.innerHTML = rec
      ? `<div style="border:1px solid var(--gold); border-radius:10px; overflow:hidden; background:rgba(255,200,0,0.08);">
           <img src="./hof-home-invasion.jpg" alt="Biggest Home Invasion Ever" style="width:100%; height:90px; object-fit:cover; display:block;">
           <div style="padding:14px; text-align:center;">
             <div style="font-size:0.72rem; color:var(--gold); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px;">💥 Biggest Home Invasion Ever</div>
             <div style="font-weight:700;">${escapeHtml(rec.attacker)} killed ${rec.thugsKilled.toLocaleString()} of ${escapeHtml(rec.defender)}'s thugs</div>
             <div style="font-size:0.78rem; color:var(--text-dim); margin-top:4px;">£${rec.cashWon.toLocaleString()} taken in the raid</div>
           </div>
         </div>`
      : `<div class="hint" style="text-align:center;">No home invasion record set yet — be the first to wipe out a rival's crew.</div>`;

    const entries = [{
      id: null, name: state.name || 'Big Boss', isYou: true,
      statsThugsKilled: state.statsThugsKilled || 0,
      statsFactoriesDestroyed: state.statsFactoriesDestroyed || 0,
      statsMoneyStolen: state.statsMoneyStolen || 0,
      hoes: state.hoes || 0,
      statsCarsStolen: state.statsCarsStolen || 0,
      lifetimeEarnings: state.lifetimeEarnings || 0,
    }];
    (state.bots || []).forEach(b => {
      if(!b.isHuman) return;
      entries.push({
        id: b.id, name: b.boss, isYou: false,
        statsThugsKilled: b.statsThugsKilled || 0,
        statsFactoriesDestroyed: b.statsFactoriesDestroyed || 0,
        statsMoneyStolen: b.statsMoneyStolen || 0,
        hoes: b.hoes || 0,
        statsCarsStolen: b.statsCarsStolen || 0,
        lifetimeEarnings: b.lifetimeEarnings || 0,
      });
    });

    const boards = [
      {key:'statsThugsKilled', achievementId:'most_thugs_killed', title:'💀 Most Thugs Killed', fmt: v => v.toLocaleString(), banner:'./hof-most-thugs-killed.jpg'},
      {key:'statsFactoriesDestroyed', achievementId:'most_factories_destroyed', title:'🧨 Most Factories Destroyed', fmt: v => v.toLocaleString(), banner:'./hof-most-factories-destroyed.jpg'},
      {key:'statsMoneyStolen', achievementId:'most_money_stolen', title:'Most Money Stolen', titleImg:'./cash-icon.jpg', fmt: v => fmtMoney(v), banner:'./hof-most-money-stolen.jpg'},
      {key:'hoes', achievementId:'most_hoes', title:'Most Hoes', titleImg:'./hoes-icon.png', fmt: v => Math.floor(v).toLocaleString(), banner:'./hof-most-hoes.jpg'},
      {key:'statsCarsStolen', achievementId:'most_cars_stolen', title:'🚗 Most Cars Stolen', fmt: v => v.toLocaleString(), banner:'./hof-most-cars-stolen.jpg'},
      {key:'lifetimeEarnings', achievementId:'top_earner', title:'📈 All Time Earnings', fmt: v => fmtMoney(v), banner:'./hof-lifetime-earnings.jpg', hideValue: true},
    ];

    const finalResults = state.seasonPrizeResults || [];
    const resultsByAchievement = Object.fromEntries(finalResults.map(r => [r.achievementId, r]));
    const subtitleEl = document.getElementById('hofSubtitle');
    if(subtitleEl){
      subtitleEl.textContent = finalResults.length
        ? '🏆 Season over — final winners are locked in below, permanently.'
        : 'Elite prizes — whoever\'s #1 in each category when the game ends gets that banner locked onto their profile forever. Standings below are live, but nothing\'s awarded until the game is over.';
    }

    container.innerHTML = boards.map(board => {
      const top = entries.filter(e => e[board.key] > 0).sort((a,b) => b[board.key] - a[board.key]).slice(0, 5);
      const rows = top.length ? top.map((e, i) => `
        <div style="display:flex; justify-content:space-between; padding:4px 0; ${e.isYou ? 'color:var(--gold); font-weight:700;' : ''}">
          <span>${i+1}. ${!e.isYou ? `<span data-profile-id="${e.id}" style="cursor:pointer; text-decoration:underline dotted;">${escapeHtml(e.name)}</span>` : escapeHtml(e.name)}</span>
          <span>${board.hideValue ? '<span style="color:var(--danger); font-weight:700;">CLASSIFIED</span>' : board.fmt(e[board.key])}</span>
        </div>
      `).join('') : `<div class="hint">No records yet.</div>`;
      const winner = resultsByAchievement[board.achievementId];
      const winnerBanner = winner
        ? `<div style="background:rgba(255,200,0,0.15); border:1px solid var(--gold); border-radius:6px; padding:6px 8px; margin-bottom:8px; font-size:0.78rem; color:var(--gold); font-weight:700;">🏆 FINAL: ${escapeHtml(winner.pimpName)}</div>`
        : '';
      const ach = ACHIEVEMENTS_BY_ID[board.achievementId];
      const prizeLine = (!winner && ach)
        ? `<div style="font-size:0.72rem; color:var(--gold); margin-bottom:8px;">🔒 Season prize: +${ach.xp} XP · +${achievementMobDollars(ach.xp)} 🪙 Mob Dollars</div>`
        : '';
      return `
        <div style="border:1px solid ${winner ? 'var(--gold)' : 'var(--panel-line)'}; border-radius:10px; overflow:hidden; background:var(--bg-2);">
          ${board.banner ? `<img src="${board.banner}" alt="${escapeHtml(board.title)}" style="width:100%; height:90px; object-fit:cover; display:block;">` : ''}
          <div style="padding:12px;">
            <div style="font-weight:700; margin-bottom:8px; font-size:0.85rem;">${board.titleImg ? `<img src="${board.titleImg}" alt="" style="height:1.1em; width:1.1em; object-fit:cover; object-position:top center; border-radius:50%; vertical-align:-3px;"> ` : ''}${escapeHtml(board.title)}</div>
            ${winnerBanner}
            ${prizeLine}
            ${rows}
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('[data-profile-id]').forEach(el => {
      el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
    });
  }

  // Respect: a pure points score, nothing to do with net worth. Computed
  // client-side from the same lifetime stat counters the server tracks for
  // Hall of Fame, so it's always in sync with whatever `state`/`state.bots`
  // last synced. AI bots never generate these stats themselves (only real
  // players taking actions do), so — same as Hall of Fame — this only ever
  // has something to show for isHuman entries.
  function computeRespect(e){
    return (e.statsJobsSucceeded || 0) * 3
      + Math.floor((e.statsTurnsWorked || 0) / 10)
      + Math.floor((e.statsThugsKilled || 0) / 1000)
      + (e.statsFactoriesDestroyed || 0);
  }

  function renderRespectLeaderboard(){
    const list = document.getElementById('respectList');
    if(!list) return;

    const rosterIds = crewRosterIds();
    const entries = [{
      id: null, name: state.name || 'Big Boss', isYou: true,
      gang: state.gang || '', emblem: (state.crewRoster && state.crewRoster.emblem) || '',
      respect: computeRespect(state),
    }];
    (state.bots || []).forEach(b => {
      if(!b.isHuman) return;
      // Recruited bots fly your crew's colors, not their old street gang.
      const inYourCrew = rosterIds.has(b.id);
      entries.push({
        id: b.id, name: b.boss, isYou: false,
        gang: inYourCrew ? (state.gang || '') : (b.gang || ''),
        emblem: inYourCrew ? ((state.crewRoster && state.crewRoster.emblem) || '') : ((state.botCrewEmblems || {})[b.gang] || ''),
        respect: computeRespect(b),
      });
    });
    entries.sort((a, b) => b.respect - a.respect);

    const rankTier = i => i === 0 ? 'lb-gold' : i === 1 ? 'lb-silver' : i === 2 ? 'lb-bronze' : '';
    const rankMedal = i => i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : '';
    list.innerHTML = entries.map((r, i) => `
      <div class="lb-row lb-respectview ${r.isYou ? 'lb-you' : ''}">
        <div class="lb-rank ${rankTier(i)}">${rankMedal(i)}${ordinal(i + 1)}</div>
        <div class="lb-name">${!r.isYou ? `<span data-profile-id="${r.id}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(r.name)}</span>` : escapeHtml(r.name)}</div>
        <div class="lb-gang">${r.gang ? `${r.emblem ? emblemInlineHtml(r.emblem) + ' ' : ''}${escapeHtml(r.gang)}` : '—'}</div>
        <div class="lb-respect">${r.respect.toLocaleString('en-GB')}</div>
      </div>
    `).join('');

    list.querySelectorAll('[data-profile-id]').forEach(el => {
      el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
    });
  }

  async function renderOnlinePlayers(){
    const list = document.getElementById('onlineList');
    if(!list) return;
    list.innerHTML = '<div class="hint">Loading...</div>';
    try{
      const res = await fetch('/api/online');
      const data = await res.json();
      if(!data.success){
        list.innerHTML = `<div class="hint">${escapeHtml(data.error || 'Could not load')}</div>`;
        return;
      }
      const entries = data.online || [];
      list.innerHTML = entries.length
        ? entries.map(r => `
            <div class="lb-row lb-onlineview">
              <div class="lb-name"><span class="lb-presence-dot online"></span>${escapeHtml(r.name)}</div>
              <div class="lb-city">${escapeHtml(r.city)}</div>
              <div class="lb-nw">${fmtMoney(r.netWorth)}</div>
              <div class="lb-stat">${escapeHtml(r.page)}</div>
            </div>
          `).join('')
        : '<div class="hint">Nobody\'s online right now (or everyone currently on is lying low).</div>';
    } catch(e){
      list.innerHTML = '<div class="hint">Could not load who\'s online.</div>';
    }
  }

  const HEIST_JOB_COOLDOWN_HOURS = 6;


  async function runHeist(jobId){
    const job = HEIST_JOBS[jobId];
    if(!job) return;
    let data;
    try{
      data = await apiCall('/api/heist', {jobId});
    } catch(e){ return; /* toast already shown */ }

    const r = data.result;
    const won = r.won;
    const cashWon = r.cashWon || 0;
    const thugsLost = r.thugsLost || 0;
    const heat = job.heatMsg[Math.floor(Math.random()*job.heatMsg.length)];

    render();

    document.getElementById('heistResultIcon').textContent = won ? job.emoji : '🚨';
    document.getElementById('heistResultTitle').textContent = won ? 'Job Complete' : 'Crew Got Wrecked';
    document.getElementById('heistResultSub').textContent = won
      ? `The ${job.name} job paid out.`
      : `The ${job.name} job went bad. Heat level: ${heat}.`;
    document.getElementById('hrCash').textContent = won ? fmtMoney(cashWon) : '£0';
    document.getElementById('hrThugsLost').textContent = thugsLost;
    document.getElementById('hrThugsLeft').textContent = state.thugs;
    document.getElementById('hrHeat').textContent = heat;
    document.getElementById('heistResultEvent').textContent = won
      ? `Your crew hit the ${job.name}, overpowered the staff, and cleared the place out in under ${2 + Math.floor(Math.random()*5)} minutes. ${thugsLost > 0 ? `${thugsLost} of your boys didn't make it back.` : 'Nobody dropped — clean exit.'} Heat level: ${heat}.`
      : `It went wrong the moment you walked in. ${thugsLost} of your crew got dropped — either by security or the police. The rest scattered. Nothing to show for it. Heat level: ${heat}.`;
    document.getElementById('heistResultEvent').className = `results-event ${won ? 'good' : 'bad'}`;
    showPage('page-heist-result');
  }

  async function runCasinoHeist(){
    const job = CASINO_JOB;
    const crewSize = state.crewMembers.length;
    let data;
    try{
      data = await apiCall('/api/heist/casino');
    } catch(e){ return; /* toast already shown */ }

    const r = data.result;
    const won = r.won;
    const cashWon = r.playerShare || 0;
    const thugsLost = r.thugsLost || 0;
    const heat = job.heatMsg[Math.floor(Math.random()*job.heatMsg.length)];

    render();

    document.getElementById('heistResultIcon').textContent = won ? job.emoji : '🚨';
    document.getElementById('heistResultTitle').textContent = won ? 'Vault Cracked!' : 'Lockdown!';
    document.getElementById('heistResultSub').textContent = won
      ? `The ${job.name} was a legendary score.`
      : `The ${job.name} went down in flames. Every cop in the city is looking for you.`;
    document.getElementById('hrCash').textContent = won ? fmtMoney(cashWon) : '£0';
    document.getElementById('hrThugsLost').textContent = thugsLost;
    document.getElementById('hrThugsLeft').textContent = state.thugs;
    document.getElementById('hrHeat').textContent = heat;
    document.getElementById('heistResultEvent').textContent = won
      ? `Your ${crewSize}-member crew coordinated the hit perfectly. Security was overpowered in minutes. You walked out with a fortune and only ${thugsLost} casualties. LEGENDARY. Heat level: ${heat}.`
      : `The casino had more thugs than expected. Your crew got pinned down. Security and police response was overwhelming. ${thugsLost} didn't make it out. Heat level: ${heat}.`;
    document.getElementById('heistResultEvent').className = `results-event ${won ? 'good' : 'bad'}`;
    showPage('page-heist-result');
  }

  function fmtMoney(n){
    return '£' + Math.round(n).toLocaleString('en-GB');
  }

  // Tweens an element's displayed number from its last rendered value to
  // `newValue` instead of snapping straight to it. `formatFn` receives the
  // in-progress numeric value each frame (already includes any interpolation).
  const _numberAnimFrames = new WeakMap();
  function animateNumberTo(el, newValue, formatFn){
    if(!el) return;
    const prevRaw = el.dataset.rawValue;
    const from = prevRaw === undefined ? newValue : parseFloat(prevRaw);
    el.dataset.rawValue = newValue;
    if(_numberAnimFrames.has(el)){
      cancelAnimationFrame(_numberAnimFrames.get(el));
      _numberAnimFrames.delete(el);
    }
    if(isNaN(from) || from === newValue){
      el.textContent = formatFn(newValue);
      return;
    }
    const duration = 400;
    const start = performance.now();
    function step(now){
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = formatFn(from + (newValue - from) * eased);
      if(t < 1){
        _numberAnimFrames.set(el, requestAnimationFrame(step));
      } else {
        el.textContent = formatFn(newValue);
        _numberAnimFrames.delete(el);
      }
    }
    _numberAnimFrames.set(el, requestAnimationFrame(step));
  }


  function totalNetWorth(){
    return calcNetWorth();
  }

  function renderXP(){
    const r = state.rankInfo;
    if(!r) return;
    document.getElementById('xpRankName').textContent = `Lv.${r.level} ${r.name}`;
    const fill = document.getElementById('xpBarFill');
    const nextLabel = document.getElementById('xpNextLabel');
    if(r.nextName){
      const pct = r.xpForLevel > 0 ? Math.min(100, Math.max(0, (r.xpIntoLevel / r.xpForLevel) * 100)) : 100;
      fill.style.width = pct + '%';
      nextLabel.textContent = `${r.xpToNext.toLocaleString()} XP to ${r.nextName}`;
    } else {
      fill.style.width = '100%';
      nextLabel.textContent = `${r.xp.toLocaleString()} XP · MAX RANK`;
    }
  }

  function addLog(msg, cls){
    const time = new Date().toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    state.log.push({t:time, msg, cls: cls||'info'});
    if(state.log.length > 60) state.log.shift();
  }

  function check24HourBonus(){
    const now = Date.now();
    const lastBonus = state.last24HourBonus || now;
    const hoursSinceBonus = (now - lastBonus) / (60 * 60 * 1000);

    if(hoursSinceBonus >= 24){
      state.turns = Math.min(state.maxTurns || 4000, state.turns + 1000);
      state.last24HourBonus = now;
      addLog(`🎁 DAILY BONUS: Earned 1,000 turns! Check back tomorrow for another!`, 'good');
      showToast('🎁 +1,000 turns!');
      save();
    }
  }

  function updateTimers(){
    // World time (GMT)
    const now = new Date();
    const hours = String(now.getUTCHours()).padStart(2, '0');
    const mins = String(now.getUTCMinutes()).padStart(2, '0');
    const worldTimeEl = document.getElementById('worldTime');
    if(worldTimeEl) worldTimeEl.textContent = `${hours}:${mins} GMT`;

    // Game countdown - state.seasonEndAt is the shared server clock that
    // actually decides when Hall of Fame prizes get awarded (see
    // maybe_award_season_end_prizes in app.py); fall back to the old
    // per-player calc only if it hasn't loaded from the server yet.

    const seasonEnd = state.seasonEndAt || ((state.gameStartTime || Date.now()) + GAME_DURATION_MS);
    const remaining = Math.max(0, seasonEnd - Date.now());

    const days = Math.floor(remaining / (24 * 60 * 60 * 1000));
    const hours2 = Math.floor((remaining % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000));
    const mins2 = Math.floor((remaining % (60 * 60 * 1000)) / (60 * 1000));

    const countdownEl = document.getElementById('gameCountdown');
    if(countdownEl){
      if(remaining <= 0){
        countdownEl.textContent = '0d 0h 0m';
        countdownEl.style.color = 'var(--red)';
      } else {
        countdownEl.textContent = `${days}d ${hours2}h ${mins2}m`;
        countdownEl.style.color = remaining < 24 * 60 * 60 * 1000 ? 'var(--red)' : 'var(--gold)';
      }
    }

    // Bonus countdown (24 hours = 86,400,000ms)
    const lastBonus = state.last24HourBonus || Date.now();
    const bonusElapsed = Date.now() - lastBonus;
    const bonusRemaining = Math.max(0, 24 * 60 * 60 * 1000 - bonusElapsed);

    const bonusHours = Math.floor(bonusRemaining / (60 * 60 * 1000));
    const bonusMins = Math.floor((bonusRemaining % (60 * 60 * 1000)) / (60 * 1000));
    const bonusSecs = Math.floor((bonusRemaining % (60 * 1000)) / 1000);

    const bonusEl = document.getElementById('bonusCountdown');
    if(bonusEl){
      if(bonusRemaining <= 0){
        bonusEl.textContent = 'READY!';
        bonusEl.style.color = 'var(--teal)';
      } else {
        bonusEl.textContent = `${bonusHours}h ${bonusMins}m ${bonusSecs}s`;
        bonusEl.style.color = bonusRemaining < 60 * 60 * 1000 ? 'var(--gold)' : 'var(--teal)';
      }
    }

    updateBuyMobDollarsCountdown();
  }

  function render(){
    updateBackgroundForCity();
    updateTimers();
    check24HourBonus();
    checkThugAttrition();
    document.getElementById('playerName').textContent = state.name || 'Big Boss';
    const playerGangDiv = document.getElementById('playerGang');
    if(state.gang){
      playerGangDiv.textContent = state.gang;
      playerGangDiv.style.display = 'block';
    } else {
      playerGangDiv.style.display = 'none';
    }
    document.getElementById('playerCityRank').innerHTML = `City: <b>#${getPlayerCityRank()}</b>`;
    document.getElementById('playerGlobalRank').innerHTML = `Global: <b>#${getPlayerGlobalRank()}</b>`;

    renderXP();

    const playerNW = totalNetWorth();
    animateNumberTo(document.getElementById('playerNWValue'), playerNW, v => fmtMoney(v));

    const dashRoster = (state.crewRoster && state.crewRoster.members) || [];
    if(state.gang && dashRoster.length > 0){
      let crewTotal = 0;
      dashRoster.forEach(m => { crewTotal += m.isYou ? playerNW : m.netWorth; });
      document.getElementById('crewNWValue').textContent = fmtMoney(crewTotal);
      document.getElementById('crewNWContainer').style.display = 'flex';
    } else {
      document.getElementById('crewNWContainer').style.display = 'none';
    }

    animateNumberTo(document.getElementById('statCash'), state.cash, v => fmtMoney(v));
    document.getElementById('statHoes').textContent = state.hoes;
    document.getElementById('statThugs').textContent = state.thugs;
    animateNumberTo(document.getElementById('statTurns'), state.turns, v => `${Math.round(v)} / ${state.maxTurns}`);
    document.getElementById('mobDollarsBalance').textContent = state.mobDollars || 0;

    const turnInput = document.getElementById('turnSlider');
    turnInput.max = Math.min(150, Math.max(1, state.turns));
    if(parseInt(turnInput.value) > turnInput.max) turnInput.value = turnInput.max;

    document.getElementById('workBtn').disabled = state.turns < 1;

    updateBribeUI();
    updateLayLowUI();

    renderLocation();
    renderLog();
    renderInventory();
    renderHouseBox();
    renderCrewChat();
    renderGlobalChat();

    document.getElementById('navTravelSub').textContent = `currently in ${state.location}`;
    document.getElementById('navBlackMarketSub').textContent =
      `${Math.floor(state.gunsOwned||0)} guns · ${Math.floor(state.medsStock||0)} meds · ${Math.floor(state.cadillacs||0)} cars`;
    document.getElementById('statHoesSub').textContent = `${Math.round(state.hoeMorale || 0)}% happy`;
    document.getElementById('statThugsSub').textContent = `${Math.round(state.thugMorale || 0)}% happy`;

    const pimpNameInput = document.getElementById('pimpNameInput');
    if(pimpNameInput && pimpNameInput.value !== state.name) pimpNameInput.value = state.name;
    const crewNameInput = document.getElementById('crewNameInput');
    if(crewNameInput && crewNameInput.value !== state.gang) crewNameInput.value = state.gang;

    renderHappinessOverlay();
    updateWorkLocationUI();
    renderNavBadges();
  }

  function renderNavBadges(){
    // Crew invites are delivered as messages too (kind:'crewInvite'), so
    // this alone already covers both DMs and invites - no separate count
    // needed for state.pendingCrewInvites or it'd double up.
    const totalUnread = (state.messages || []).filter(m => m.to === 'player' && !m.read).length;
    const badge = document.getElementById('playerMsgBadge');
    if(!badge) return;
    if(totalUnread > 0){
      badge.textContent = totalUnread > 99 ? '99+' : totalUnread;
      badge.style.display = 'flex';
    } else {
      badge.style.display = 'none';
    }

    const totalFactories = Object.values(state.factories || {}).reduce((a, b) => a + b, 0);
    document.querySelectorAll('[data-page="page-production"]').forEach(el => {
      el.style.display = totalFactories > 0 ? '' : 'none';
    });
  }

  function renderBMBuyGrid(){
    const grid = document.getElementById('bmBuyGrid');
    if(!grid) return;
    grid.innerHTML = BLACKMARKET_ITEMS.filter(item => !item.sellOnly).map(item => {
      const price = item.key === 'thugs' ? thugBuyPrice() : item.price;
      const afford = Math.max(1, Math.floor(state.cash / price));
      return `
        <div class="bm-card">
          <div class="bm-art"><img src="./${encodeURIComponent(item.img)}" alt="${item.name}"></div>
          <div class="bm-head">
            <div class="bm-name">${item.name}</div>
          </div>
          <div class="bm-price">Cost: <b>${fmtMoney(price)}</b> each</div>
          <div class="ho-qty-row"><span>Qty to buy</span><b class="bmBuyLabel-${item.key}">1</b></div>
          <div class="bm-qty">
            <input type="number" class="bmBuySlider-${item.key}" min="1" max="${afford}" value="1">
          </div>
          <div class="bm-total">Total: <b class="bmBuyTotal-${item.key}">${fmtMoney(price)}</b></div>
          <button class="cta cta-buy" data-bmbuy="${item.key}" ${state.cash < price ? 'disabled' : ''}>Buy</button>
        </div>`;
    }).join('');

    BLACKMARKET_ITEMS.filter(item => !item.sellOnly).forEach(item => {
      const slider = grid.querySelector(`.bmBuySlider-${item.key}`);
      const label = grid.querySelector(`.bmBuyLabel-${item.key}`);
      const total = grid.querySelector(`.bmBuyTotal-${item.key}`);
      const updateDisplay = () => {
        const qty = parseInt(slider.value) || 1;
        label.textContent = qty;
        const unitPrice = item.key === 'thugs' ? thugBuyPrice() : item.price;
        total.textContent = fmtMoney(qty * unitPrice);
      };
      slider.addEventListener('input', updateDisplay);
      updateDisplay();
    });

    grid.querySelectorAll('[data-bmbuy]').forEach(btn => {
      btn.addEventListener('click', () => buyBlackMarketItem(btn.dataset.bmbuy));
    });
  }

  async function buyBlackMarketItem(key){
    const slider = document.querySelector(`.bmBuySlider-${key}`);
    const qty = parseInt(slider.value) || 1;
    try{
      const data = await apiCall('/api/blackmarket/buy', {key, qty});
      showToast(`Bought for ${fmtMoney(data.result.totalCost)}.`);
      render(); renderBlackMarket();
    } catch(e){ /* toast already shown */ }
  }

  function renderBlackMarket(){
    renderBMBuyGrid();
    const grid = document.getElementById('bmGrid');
    if(!grid) return;
    ensureMarket();
    grid.innerHTML = BLACKMARKET_ITEMS.map(item => {
      const owned = Math.floor(getStock(item));
      const price = currentPrice(item);
      return `
        <div class="bm-card">
          <div class="bm-art"><img src="./${encodeURIComponent(item.img)}" alt="${item.name}"></div>
          <div class="bm-head">
            <div class="bm-name">${item.name}</div>
          </div>
          <div class="bm-owned">In stock: <b>${owned}</b></div>
          <div class="bm-price">Fence pays <b>${fmtMoney(price)}</b> each</div>
          <div class="bm-qty">
            <input type="number" min="0" max="${owned}" value="${owned > 0 ? 1 : 0}" data-qty="${item.key}">
          </div>
          <div class="bm-quickbtns">
            <button data-qtybtn="${item.key}" data-v="1">1</button>
            <button data-qtybtn="${item.key}" data-v="10">10</button>
            <button data-qtybtn="${item.key}" data-v="max">MAX</button>
          </div>
          <div class="bm-total">Payout: <b id="bmTotal-${item.key}">£0</b></div>
          <button class="bm-sell-btn" data-sell="${item.key}" ${owned < 1 ? 'disabled' : ''}>Sell</button>
        </div>`;
    }).join('');

    BLACKMARKET_ITEMS.forEach(item => {
      const input = grid.querySelector(`[data-qty="${item.key}"]`);
      const updateTotal = () => {
        const owned = Math.floor(getStock(item));
        let qty = Math.floor(Number(input.value)) || 0;
        qty = Math.max(0, Math.min(qty, owned));
        input.value = qty;
        document.getElementById(`bmTotal-${item.key}`).textContent = fmtMoney(qty * currentPrice(item));
      };
      input.addEventListener('input', updateTotal);
      updateTotal();
    });

    grid.querySelectorAll('[data-qtybtn]').forEach(btn => {
      btn.addEventListener('click', () => {
        const item = BLACKMARKET_ITEMS.find(i => i.key === btn.dataset.qtybtn);
        const owned = Math.floor(getStock(item));
        const input = grid.querySelector(`[data-qty="${item.key}"]`);
        input.value = btn.dataset.v === 'max' ? owned : Math.min(owned, parseInt(btn.dataset.v));
        input.dispatchEvent(new Event('input'));
      });
    });

    grid.querySelectorAll('[data-sell]').forEach(btn => {
      btn.addEventListener('click', () => sellBlackMarket(btn.dataset.sell));
    });

    renderMarketGrid();
  }

  async function sellBlackMarket(key){
    const input = document.querySelector(`[data-qty="${key}"]`);
    let qty = Math.floor(Number(input.value)) || 0;
    if(qty < 1) return;
    try{
      const data = await apiCall('/api/blackmarket/sell', {key, qty});
      showToast(`Sold for ${fmtMoney(data.result.payout)}.`);
      render(); renderBlackMarket();
    } catch(e){ /* toast already shown */ }
  }

  function renderMarketGrid(){
    const grid = document.getElementById('marketGrid');
    if(!grid) return;
    ensureMarket();
    const now = Date.now();
    const nextMs = MARKET_MS - ((now - state.lastMarketUpdate) % MARKET_MS);
    const nextMins = Math.max(0, Math.ceil(nextMs / 60000));

    grid.innerHTML = BLACKMARKET_ITEMS.map(item => {
      const m = state.market[item.key];
      const hist = m.history.length > 1 ? m.history : [1, m.mult];
      const prev = hist[hist.length - 2];
      const cur = hist[hist.length - 1];
      const pct = prev ? ((cur - prev) / prev) * 100 : 0;
      const trend = pct >= 0 ? 'up' : 'down';
      const price = Math.max(1, Math.round(item.price * cur));

      const w = 100, h = 32;
      const min = Math.min(...hist), max = Math.max(...hist);
      const stepX = hist.length > 1 ? w / (hist.length - 1) : w;
      const pts = hist.map((v, i) => {
        const x = i * stepX;
        const y = max > min ? h - ((v - min) / (max - min)) * h : h / 2;
        return [Math.round(x*100)/100, Math.round(y*100)/100];
      });
      const linePts = pts.map(p => p.join(',')).join(' ');
      const areaPath = `M${pts[0][0]},${h} L${pts.map(p => p.join(',')).join(' L')} L${pts[pts.length-1][0]},${h} Z`;

      return `
        <div class="market-card">
          <div class="market-top">
            <div class="market-name">${item.name}</div>
            <div class="market-change ${trend}">${pct >= 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%</div>
          </div>
          <div class="market-price">${fmtMoney(price)}</div>
          <svg class="market-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
            <path class="fill ${trend}" d="${areaPath}"></path>
            <polyline class="line ${trend}" points="${linePts}"></polyline>
          </svg>
          <div class="market-sub">next move in ~${nextMins} min</div>
        </div>`;
    }).join('');
  }


  function thugMoraleMult(){ return 0.5 + (state.thugMorale / 100); }

  // every 10 turns worked, gain 1-3 new hoes (flat rate, independent of current roster size)

  function carFactoryOutputRates(ratio){
    ratio = Math.max(0, Math.min(1, ratio));
    return {
      cadillacRate: CAR_FACTORY_CADILLAC_AT_MIN + (CAR_FACTORY_CADILLAC_AT_MAX - CAR_FACTORY_CADILLAC_AT_MIN) * ratio,
      armoredRate: CAR_FACTORY_ARMORED_AT_MIN + (CAR_FACTORY_ARMORED_AT_MAX - CAR_FACTORY_ARMORED_AT_MIN) * ratio,
    };
  }



  function gunFactoryOutputRates(ratio){
    ratio = Math.max(0, Math.min(1, ratio));
    return {
      pistolRate: GUN_FACTORY_PISTOL_AT_VOLUME + (GUN_FACTORY_PISTOL_AT_ELITE - GUN_FACTORY_PISTOL_AT_VOLUME) * ratio,
      shotgunRate: GUN_FACTORY_SHOTGUN_AT_VOLUME + (GUN_FACTORY_SHOTGUN_AT_ELITE - GUN_FACTORY_SHOTGUN_AT_VOLUME) * ratio,
      akRate: GUN_FACTORY_AK_AT_VOLUME + (GUN_FACTORY_AK_AT_ELITE - GUN_FACTORY_AK_AT_VOLUME) * ratio,
      m249Rate: GUN_FACTORY_M249_AT_VOLUME + (GUN_FACTORY_M249_AT_ELITE - GUN_FACTORY_M249_AT_VOLUME) * ratio,
    };
  }


  function fmtLogTime(t){
    const d = new Date(t);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${hh}:${mm}:${ss}`;
  }

  function renderLog(){
    const body = document.getElementById('logBody');
    body.innerHTML = state.log.map(l =>
      `<div class="logline ${l.cls}"><span class="ts">[${fmtLogTime(l.t)}]</span>${escapeHtml(l.msg)}</div>`
    ).join('');
    const term = document.getElementById('terminal');
    term.scrollTop = term.scrollHeight;
  }

  // Net worth thresholds for the house progression under All-Time Earnings.
  // Each tier's photo unlocks once net worth reaches its threshold; you're
  // always shown the highest tier you currently qualify for.
  const HOUSE_TIERS = [
    {img: './houses/1.jpg', threshold: 0},
    {img: './houses/2.jpg', threshold: 1000000},
    {img: './houses/3.jpg', threshold: 50000000},
    {img: './houses/4.jpg', threshold: 120000000},
    {img: './houses/5.jpg', threshold: 300000000},
    {img: './houses/6.jpg', threshold: 1000000000},
    {img: './houses/7.jpg', threshold: 5000000000},
    {img: './houses/8.jpg', threshold: 15000000000},
    {img: './houses/9.jpg', threshold: 30000000000},
    {img: './houses/10.jpg', threshold: 50000000000},
  ];

  function currentHouseTier(netWorth){
    let tier = HOUSE_TIERS[0];
    let tierNum = 1;
    for(let i = 0; i < HOUSE_TIERS.length; i++){
      if(netWorth >= HOUSE_TIERS[i].threshold){ tier = HOUSE_TIERS[i]; tierNum = i + 1; }
    }
    return {img: tier.img, tierNum};
  }

  function renderInventory(){
    const list = document.getElementById('inventoryList');
    if(!list) return;
    const f = state.factories || {};
    const g = state.guns || {};
    const rows = [
      ['Medical Factories', f.medical || 0],
      ['Gun Factories', f.gun || 0],
      ['Car Factories', f.car || 0],
      ['Drug Factories', f.drug || 0],
      ['Explosive Factories', f.explosive || 0],
      ['Counterfeit Factories', f.counterfeit || 0],
      ['Gym Factories', f.gym || 0],
      ['9mm Pistols', g.pistol9mm || 0],
      ['12 Gauge Shotguns', g.shotgun12gauge || 0],
      ['AK-47s', g.ak47 || 0],
      ['M249s', g.m249 || 0],
      ['Cadillacs', state.cadillacs || 0],
      ['Armored Trucks', state.armoredTrucks || 0],
      ['Meds Stockpile', Math.floor(state.medsStock || 0)],
      ['Bombs', Math.floor(state.bombs || 0)],
      ['Cocaine', Math.floor((state.drugs || {}).coke || 0)],
    ];
    list.innerHTML = rows.map(([label, val]) => `
      <div class="logline info inv-row"><span>${label}</span><span class="inv-val">${val}</span></div>
    `).join('') + `
      <div class="logline good inv-row"><span>Counterfeit Earned</span><span class="inv-val">${fmtMoney(state.counterfeitEarnings || 0)}</span></div>
      <div class="logline money inv-row inv-total"><span>All-Time Earnings</span><span class="inv-val">${fmtMoney(state.lifetimeEarnings || 0)}</span></div>
    `;
  }

  function renderCrewChat(){
    const box = document.getElementById('crewChatBox');
    const list = document.getElementById('crewChatMessages');
    if(!box || !list) return;
    if(!state.gang){
      box.style.display = 'none';
      return;
    }
    box.style.display = 'block';

    const messages = (state.crewRoster && state.crewRoster.chat) || [];
    const wasNearBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) < 40;
    list.innerHTML = messages.length
      ? messages.map(m => `
          <div class="crew-chat-msg ${currentUser && m.userId === currentUser.id ? 'you' : ''}">
            <span class="crew-chat-msg-name">${escapeHtml(m.name)}</span><span class="crew-chat-msg-time">${timeAgo(m.timestamp)}</span>
            <div>${escapeHtml(m.text)}</div>
          </div>
        `).join('')
      : '<div class="hint">No messages yet — say something to your crew.</div>';
    if(wasNearBottom) list.scrollTop = list.scrollHeight;
  }

  async function sendCrewChatMessage(){
    const input = document.getElementById('crewChatInput');
    const text = input.value.trim();
    if(!text) return;
    input.value = '';
    try{
      await apiCall('/api/crew/chat/send', {text});
      render();
    } catch(e){ /* toast already shown */ }
  }

  function renderGlobalChat(){
    const list = document.getElementById('globalChatMessages');
    if(!list) return;
    const messages = state.globalChat || [];
    const wasNearBottom = (list.scrollHeight - list.scrollTop - list.clientHeight) < 40;
    list.innerHTML = messages.length
      ? messages.map(m => `
          <div class="crew-chat-msg ${currentUser && m.userId === currentUser.id ? 'you' : ''}">
            <span class="crew-chat-msg-name">${escapeHtml(m.name)}</span><span class="crew-chat-msg-time">${timeAgo(m.timestamp)}</span>
            <div>${escapeHtml(m.text)}</div>
          </div>
        `).join('')
      : '<div class="hint">No messages yet — say hello.</div>';
    if(wasNearBottom) list.scrollTop = list.scrollHeight;
  }

  async function sendGlobalChatMessage(){
    const input = document.getElementById('globalChatInput');
    const text = input.value.trim();
    if(!text) return;
    input.value = '';
    try{
      await apiCall('/api/globalchat/send', {text});
      render();
    } catch(e){ /* toast already shown */ }
  }

  function renderHouseBox(){
    const box = document.getElementById('houseBoxContent');
    if(!box) return;
    const house = currentHouseTier(totalNetWorth());
    box.innerHTML = `
      <div class="house-box-label"><span>Your Crib</span><b>Level ${house.tierNum} / ${HOUSE_TIERS.length}</b></div>
      <img src="${house.img}" alt="Your house, level ${house.tierNum}">
    `;
  }

  function escapeHtml(s){
    return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function ordinal(n){
    const rem100 = n % 100;
    if(rem100 >= 11 && rem100 <= 13) return `${n}th`;
    switch(n % 10){
      case 1: return `${n}st`;
      case 2: return `${n}nd`;
      case 3: return `${n}rd`;
      default: return `${n}th`;
    }
  }

  function timeAgo(t){
    const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if(diffSec < 60) return 'just now';
    const diffMin = Math.floor(diffSec / 60);
    if(diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if(diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  }

  function playSiren(){
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const now = audioContext.currentTime;

      // Siren sound - alternating high/low frequencies
      for(let i = 0; i < 4; i++){
        const osc = audioContext.createOscillator();
        const gain = audioContext.createGain();

        osc.connect(gain);
        gain.connect(audioContext.destination);

        const freqLow = 600;
        const freqHigh = 1000;
        const freq = i % 2 === 0 ? freqHigh : freqLow;

        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.3, now + i * 0.3);
        gain.gain.setValueAtTime(0, now + (i + 1) * 0.3);

        osc.start(now + i * 0.3);
        osc.stop(now + (i + 1) * 0.3);
      }
    } catch(e) {
      // Audio not supported, silent fail
    }
  }

  function showGunfireAnimation(){
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position:fixed; inset:0; z-index:999; background:rgba(0,0,0,0.3);
      display:flex; align-items:center; justify-content:center;
      animation:gunfireFlash 0.8s ease-out; pointer-events:none;
    `;
    overlay.innerHTML = `
      <div style="display:flex; gap:14px; animation:gunfireShake 0.7s ease-in-out;">
        <span style="font-size:4.5rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0s;">💥🔫</span>
        <span style="font-size:4.5rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0.08s;">🔫💥</span>
        <span style="font-size:4.5rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0.16s;">💥🔫</span>
      </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.remove(), 800);
  }

  function playBombSound(){
    if(isSoundMuted()) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const now = ctx.currentTime;

      // Low sine "thump" for the body of the blast.
      const osc = ctx.createOscillator();
      const oscGain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(150, now);
      osc.frequency.exponentialRampToValueAtTime(30, now + 0.4);
      oscGain.gain.setValueAtTime(0.9, now);
      oscGain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
      osc.connect(oscGain);
      oscGain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.5);

      // Filtered noise burst for the crack/debris on top of the thump.
      const bufferSize = ctx.sampleRate * 0.6;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for(let i = 0; i < bufferSize; i++){
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / bufferSize, 2);
      }
      const noise = ctx.createBufferSource();
      noise.buffer = buffer;
      const noiseFilter = ctx.createBiquadFilter();
      noiseFilter.type = 'lowpass';
      noiseFilter.frequency.setValueAtTime(1800, now);
      noiseFilter.frequency.exponentialRampToValueAtTime(200, now + 0.6);
      const noiseGain = ctx.createGain();
      noiseGain.gain.setValueAtTime(0.8, now);
      noiseGain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
      noise.connect(noiseFilter);
      noiseFilter.connect(noiseGain);
      noiseGain.connect(ctx.destination);
      noise.start(now);
    } catch(e) {
      // Audio not supported, silent fail
    }
  }

  function showExplosionAnimation(){
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position:fixed; inset:0; z-index:999; background:rgba(0,0,0,0.3);
      display:flex; align-items:center; justify-content:center;
      animation:gunfireFlash 0.8s ease-out; pointer-events:none;
    `;
    overlay.innerHTML = `
      <div style="display:flex; gap:14px; animation:gunfireShake 0.7s ease-in-out;">
        <span style="font-size:5rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0s;">💥</span>
        <span style="font-size:6rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0.08s;">🔥</span>
        <span style="font-size:5rem; display:inline-block; animation:muzzleFlashPop 0.7s ease-out 0.16s;">💥</span>
      </div>
    `;
    document.body.appendChild(overlay);
    setTimeout(() => overlay.remove(), 800);
  }

  function showPoliceAnimation(){
    // Create police overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position:fixed; inset:0; z-index:999; background:rgba(0,0,0,0.3);
      display:flex; align-items:center; justify-content:center;
      animation:policeFlash 2s ease-out;
    `;

    overlay.innerHTML = `
      <div style="font-size:8rem; animation:policeShake 0.5s ease-in-out infinite;">🚔</div>
    `;

    document.body.appendChild(overlay);
    setTimeout(() => overlay.remove(), 2000);
  }

  function showToast(msg){
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(()=>t.classList.remove('show'), 1800);
  }

  // ---- Actions ----
  async function setWorkLocation(loc){
    try{
      await apiCall('/api/work/location', {location: loc});
      updateWorkLocationUI();
    } catch(e){ /* toast already shown */ }
  }

  function showWorkResults(data){
    if(!state.showWorkResults) return;
    const modal = document.getElementById('workResultsModal');
    if(!modal) return;

    const resultsHTML = `
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:center;">
        <div style="font-family:'IBM Plex Mono',monospace;">
          <div style="font-size:0.9rem; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Hoes</span>
              <span style="color:var(--teal); font-weight:700;">+${data.hoesGain}${data.hoesLost ? ` <span style="color:var(--red);">-${data.hoesLost} (low morale)</span>` : ''}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Thugs</span>
              <span style="color:var(--teal); font-weight:700;">+${data.thugsGain}${data.thugsLost ? ` <span style="color:var(--red);">-${data.thugsLost}</span>` : ''}</span>
            </div>
            ${data.busted ? `
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Heat</span>
              <span style="color:var(--red); font-weight:700;">🚨 BUSTED!</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Lost</span>
              <span style="color:var(--red); font-weight:700;">-${fmtMoney(data.cashLost)}</span>
            </div>
            ` : ''}
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Hoe Wages</span>
              <span style="color:var(--red); font-weight:700;">-${fmtMoney(data.hoeWage || 0)}</span>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom:8px; padding:8px; background:var(--bg-2); border-radius:4px;">
              <span style="color:var(--text-dim);">Earned</span>
              <span style="color:var(--gold); font-weight:700;">+${fmtMoney(data.cashGain)}</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:12px; background:var(--panel-line); border-radius:4px; border:2px solid ${data.busted ? 'var(--red)' : 'var(--teal)'}; margin-top:12px;">
              <span style="color:#fff; font-weight:700;">Net Gain</span>
              <span style="color:${data.busted ? 'var(--red)' : 'var(--gold)'}; font-weight:700; font-size:1.2rem;">+${fmtMoney(data.cashGain - (data.cashLost || 0))}</span>
            </div>
          </div>
        </div>
        <div style="text-align:center;">
          <div style="width:100%; height:280px; background:linear-gradient(135deg, #1a1a2e, #16213e); border-radius:8px; overflow:hidden;">
            <img src="./hoes.png" alt="Hoes" style="width:100%; height:100%; object-fit:contain; display:block;">
          </div>
        </div>
      </div>
    `;

    document.getElementById('workResultsContent').innerHTML = resultsHTML;
    modal.classList.remove('hidden');
  }

  function updateWorkLocationUI(){
    const redBtn = document.getElementById('locRedLight');
    const nightBtn = document.getElementById('locNightclub');
    const pullBtn = document.getElementById('locPullup');

    // Traffic-light system: Red Light = red, Nightclub = yellow, Pull Up =
    // green - always tinted, not just when selected. The active location
    // gets the bright/saturated version; the other two stay dim.
    function paint(btn, active, dim, bright, textOnBright){
      btn.style.background = active ? bright : dim;
      btn.style.border = `2px solid ${bright}`;
      btn.style.color = active ? textOnBright : '#fff';
      btn.style.fontWeight = active ? '700' : '600';
    }

    paint(redBtn, state.workLocation === 'redlight', '#5c0000', '#ff1744', '#fff');
    paint(nightBtn, state.workLocation === 'nightclub', '#665400', '#ffd700', '#000');
    paint(pullBtn, state.workLocation === 'pullup', '#0f5c1f', '#2fe08a', '#000');
  }

  function checkThugAttrition(){
    if(state.thugMorale <= 0 && state.thugs > 0){
      const lost = Math.max(1, Math.ceil(state.thugs * 0.05)); // lose 5% per cycle
      state.thugs = Math.max(0, state.thugs - lost);
      addLog(`⚠️ ${lost} thugs left due to low morale — keep them happy!`, 'bad');
    }
  }

  async function workBlock(){
    const turns = Math.min(150, parseInt(document.getElementById('turnSlider').value) || 0, state.turns);
    if(turns < 1) return;
    let data;
    try{
      data = await apiCall('/api/work', {turns});
    } catch(e){ return; /* toast already shown */ }

    const r = data.result;
    if(r.busted){
      showPoliceAnimation();
      playSiren();
    }
    showWorkResults(r);

    render();
  }


  function openMobDollarsModal(){
    const slider = document.getElementById('mobDollarsSlider');
    slider.max = state.mobDollars || 0;
    slider.value = 0;
    updateMobDollarsModal();
    updateBuyMobDollarsCountdown();
    document.getElementById('mobDollarsModal').classList.remove('hidden');
  }

  function updateMobDollarsModal(){
    document.getElementById('mobDollarsModalBalance').textContent = state.mobDollars || 0;
    const slider = document.getElementById('mobDollarsSlider');
    const amt = parseInt(slider.value) || 0;
    document.getElementById('mobDollarsTurnsPreview').textContent = `${amt * MOB_DOLLARS_TURNS_PER_UNIT} turns`;
  }

  async function spendMobDollars(){
    const slider = document.getElementById('mobDollarsSlider');
    const amt = parseInt(slider.value) || 0;
    if(amt < 1) return;
    try{
      await apiCall('/api/mobdollars/spend', {amount: amt});
      showToast(`Spent ${amt} 🪙 Mob Dollars on turns.`);
      render();
      openMobDollarsModal();
    } catch(e){ /* toast already shown */ }
  }

  async function savePimpName(){
    const nameInput = document.getElementById('pimpNameInput');
    const name = nameInput.value.trim();
    if(!name) return;
    if(name === state.name) return;
    if(!confirm(`Change your name to "${name}" for 10 Mob Dollars?`)) return;
    try{
      await apiCall('/api/settings/pimpname', {name});
      showToast('Name changed successfully!');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function saveBio(){
    const bioInput = document.getElementById('bioInput');
    const bio = bioInput.value.trim();
    try{
      await apiCall('/api/settings/bio', {bio});
      showToast('Bio saved!');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function saveCrewName(){
    const crewInput = document.getElementById('crewNameInput');
    const crew = crewInput.value.trim();
    if(!crew){
      showToast('Crew name cannot be empty');
      return;
    }
    if(crew === state.gang) return;
    if(state.gang && !confirm(`Change your crew's name to "${crew}" for 10 Mob Dollars?`)) return;
    try{
      await apiCall('/api/crew/name', {name: crew});
      showToast('Crew name saved!');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function inviteToCrewFromLeaderboard(botId){
    try{
      const data = await apiCall('/api/crew/invite', {botId});
      if(data.result && data.result.sentTo){
        showToast(`✉️ Crew invite sent to ${data.result.sentTo} — waiting for them to accept.`);
      } else {
        showToast('👥 Crew member added!');
      }
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function acceptCrewInvite(fromUserId){
    try{
      const data = await apiCall('/api/crew/invite/accept', {fromUserId});
      showToast(`👥 You joined "${data.result.gang}"!`);
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function declineCrewInvite(fromUserId){
    try{
      await apiCall('/api/crew/invite/decline', {fromUserId});
      showToast('Invite declined.');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function removeFromCrew(botId){
    try{
      await apiCall('/api/crew/remove', {botId});
      showToast('👋 Member removed');
      render();
    } catch(e){ /* toast already shown */ }
  }

  function openProfile(botId){
    // Bots don't have accounts/profiles - only real players do.
    const bot = state.bots.find(b => b.id === botId);
    if(!bot || !bot.isHuman) return;
    navigateTo('page-profile');
    loadProfile(botId);
  }

  function openOwnProfile(){
    if(!state || !state.selfProfileId) return;
    navigateTo('page-profile');
    loadProfile(state.selfProfileId);
  }

  async function loadProfile(botId){
    const container = document.getElementById('profileContent');
    container.innerHTML = '<div class="hint">Loading...</div>';
    try{
      const res = await fetch(`/api/profile/${botId}`);
      const data = await res.json();
      if(!data.success){
        container.innerHTML = `<div class="hint">${escapeHtml(data.error || 'Could not load profile')}</div>`;
        return;
      }
      const p = data.profile;
      document.getElementById('profileSubtitle').textContent = p.isSelf
        ? 'This is what everyone else sees when they click your name.'
        : 'Public info only — no combat stats. Pay an Informer for the real numbers.';
      const joinDate = new Date(p.joinDate).toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric'});
      const isDon = p.rank.level >= 13;
      container.innerHTML = `
        ${isDon ? `
        <div style="text-align:center; margin-bottom:16px; padding:14px; border:2px solid var(--gold); border-radius:12px; background:linear-gradient(135deg, rgba(255,200,0,0.15), rgba(255,200,0,0.03)); box-shadow:0 0 20px rgba(255,200,0,0.35);">
          <div style="font-family:'Anton',sans-serif; font-size:1.3rem; letter-spacing:0.08em; color:var(--gold);">👑 THE DON 👑</div>
          <div style="font-size:0.72rem; color:var(--text-dim); margin-top:4px;">Reached the top of the game — a title only THE DON gets to wear.</div>
        </div>` : ''}
        <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
          <h3 style="margin:0;">${escapeHtml(p.name)}</h3>
          <div style="font-family:'Anton',sans-serif; color:var(--gold); font-size:0.9rem;">Lv.${p.rank.level} ${escapeHtml(p.rank.name)}</div>
        </div>
        ${p.bio ? `<div style="margin-bottom:16px; padding:12px; background:var(--bg-2); border:1px solid var(--panel-line); border-radius:8px; font-size:0.85rem; font-style:italic; color:var(--text); white-space:pre-wrap;">"${escapeHtml(p.bio)}"</div>` : (p.isSelf ? `<div style="margin-bottom:16px; padding:12px; background:var(--bg-2); border:1px dashed var(--panel-line); border-radius:8px; font-size:0.85rem; color:var(--text-dim);">No bio yet — add one on the Settings page.</div>` : '')}
        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:16px;">
          <div style="background:var(--bg-2); border:1px solid var(--panel-line); border-radius:8px; padding:12px;">
            <div style="font-size:0.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px;">Crew</div>
            <div style="font-weight:700;">${p.gang ? `${p.emblem ? emblemInlineHtml(p.emblem) + ' ' : ''}${escapeHtml(p.gang)}` : '—'}</div>
          </div>
          <div style="background:var(--bg-2); border:1px solid var(--panel-line); border-radius:8px; padding:12px;">
            <div style="font-size:0.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px;">Net Worth</div>
            <div style="font-weight:700; color:var(--gold);">${fmtMoney(p.netWorth)}</div>
          </div>
          <div style="background:var(--bg-2); border:1px solid var(--panel-line); border-radius:8px; padding:12px;">
            <div style="font-size:0.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px;">Joined</div>
            <div style="font-weight:700;">${joinDate}</div>
          </div>
          <div style="background:var(--bg-2); border:1px solid var(--panel-line); border-radius:8px; padding:12px;">
            <div style="font-size:0.7rem; color:var(--danger); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px; font-weight:700;">Last Attacked By</div>
            ${p.lastAttackedBy ? `
              <div style="font-weight:700; color:var(--danger);">${escapeHtml(p.lastAttackedBy.name)}</div>
              <div style="font-size:0.7rem; color:var(--danger); margin-top:2px; opacity:0.8;">${timeAgo(p.lastAttackedBy.t)} · ${p.lastAttackedBy.won ? 'won' : 'failed'}</div>
            ` : `<div style="font-weight:700; color:var(--text-dim);">—</div><div style="font-size:0.7rem; color:var(--text-dim); margin-top:2px;">No attacks yet</div>`}
          </div>
        </div>
        ${(p.achievements || []).length > 0 ? `
        <div style="margin-bottom:16px;">
          <div style="font-size:0.7rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:8px;">Badges</div>
          <div style="display:flex; flex-wrap:wrap; gap:8px;">
            ${p.achievements.map(id => {
              const a = ACHIEVEMENTS_BY_ID[id];
              if(!a) return '';
              const art = a.img
                ? `<img src="${a.img}" alt="${escapeHtml(a.name)}" style="width:40px; height:40px; object-fit:contain;">`
                : `<span style="font-size:1.6rem;">${a.emoji}</span>`;
              return `<span title="${escapeHtml(a.name)} — ${escapeHtml(a.desc)}" style="display:inline-flex; align-items:center; border:1px solid var(--gold); border-radius:8px; padding:6px 10px; background:rgba(255,200,0,0.08);">${art}</span>`;
            }).join('')}
          </div>
        </div>` : ''}
        ${p.isSelf
          ? `<div style="display:flex; gap:10px;">
               <button class="cta gold" id="profileEditNameBtn" style="flex:1;">✏️ Edit Name</button>
               <button class="cta gold" id="profileEditCrewBtn" style="flex:1;">🤝 Edit Crew</button>
             </div>`
          : `<button class="cta gold" id="profileMsgBtn" style="width:100%;">✉️ Message ${escapeHtml(p.name)}</button>`}
      `;
      if(p.isSelf){
        document.getElementById('profileEditNameBtn').addEventListener('click', () => navigateTo('page-settings'));
        document.getElementById('profileEditCrewBtn').addEventListener('click', () => navigateTo('page-crew'));
      } else {
        document.getElementById('profileMsgBtn').addEventListener('click', () => openDMModal(p.botId));
      }
    } catch(e){
      container.innerHTML = '<div class="hint">Could not load profile.</div>';
    }
  }

  function openDMModal(botId){
    const bot = state.bots.find(b => b.id === botId);
    if(!bot) return;

    const modal = document.getElementById('dmModal');
    const title = document.getElementById('dmTitle');
    const history = document.getElementById('dmHistory');
    const input = document.getElementById('dmInput');
    const sendBtn = document.getElementById('dmSendBtn');

    title.textContent = bot.boss;
    input.value = '';
    input.focus();

    // Load message history
    const conversation = state.messages.filter(m =>
      (m.from === 'player' && m.to === botId) || (m.from === botId && m.to === 'player')
    );

    history.innerHTML = conversation.map(m => {
      if(m.kind === 'attack'){
        return `
          <div style="display:flex; justify-content:center;">
            <div style="background:rgba(255,77,77,0.12); border:1px solid var(--danger); color:var(--danger); padding:8px 14px; border-radius:8px; max-width:90%; text-align:center; font-weight:700; font-size:0.85rem;">
              💥 ${escapeHtml(m.text)}
            </div>
          </div>
        `;
      }
      if(m.kind === 'crewInvite'){
        const incoming = m.to === 'player';
        const statusLabel = m.status === 'accepted' ? '✅ Accepted' : m.status === 'declined' ? '❌ Declined' : '';
        return `
          <div style="display:flex; ${m.from === 'player' ? 'justify-content:flex-end;' : 'justify-content:flex-start;'}">
            <div style="background:var(--bg-2); border:2px solid var(--gold); color:var(--text); padding:10px 14px; border-radius:8px; max-width:80%;">
              <div style="font-weight:700;">🤝 ${escapeHtml(m.text)}</div>
              ${incoming && !m.status ? `
                <div style="display:flex; gap:8px; margin-top:8px;">
                  <button class="cta gold cta-sm" data-dm-accept-invite="${m.fromUserId}" ${state.gang ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}>Accept</button>
                  <button class="cta danger cta-sm" data-dm-decline-invite="${m.fromUserId}">Decline</button>
                </div>
                ${state.gang ? `<div class="hint" style="margin-top:4px;">You're already in a crew — leave it to accept this.</div>` : ''}` : ''}
              ${statusLabel ? `<div style="font-size:0.8rem; color:var(--text-dim); margin-top:6px;">${statusLabel}</div>` : ''}
            </div>
          </div>
        `;
      }
      return `
      <div style="display:flex; ${m.from === 'player' ? 'justify-content:flex-end;' : 'justify-content:flex-start;'}">
        <div style="background:${m.from === 'player' ? 'var(--gold)' : 'var(--hot)'}; color:#000; padding:8px 12px; border-radius:8px; max-width:80%; word-wrap:break-word;">
          ${escapeHtml(m.text)}
        </div>
      </div>
    `;
    }).join('');

    history.querySelectorAll('[data-dm-accept-invite]:not(:disabled)').forEach(btn => {
      btn.addEventListener('click', async () => {
        await acceptCrewInvite(parseInt(btn.dataset.dmAcceptInvite));
        openDMModal(botId);
      });
    });
    history.querySelectorAll('[data-dm-decline-invite]').forEach(btn => {
      btn.addEventListener('click', async () => {
        await declineCrewInvite(parseInt(btn.dataset.dmDeclineInvite));
        openDMModal(botId);
      });
    });

    // Auto-scroll to bottom
    setTimeout(() => history.scrollTop = history.scrollHeight, 50);

    modal.classList.remove('hidden');

    // Opening a conversation clears its unread badge - only bother the
    // server if there's actually something unread to clear.
    if(conversation.some(m => m.from === botId && !m.read)){
      apiCall('/api/dm/read', {fromId: botId})
        .then(() => { renderNavBadges(); if(document.getElementById('page-messages').classList.contains('active')) renderMessages(); })
        .catch(() => {});
    }

    // Setup send handler - server appends the player's message plus a
    // canned bot reply, then returns the updated state.
    const sendMessage = async () => {
      const text = input.value.trim();
      if(!text) return;
      input.value = '';
      try{
        await apiCall('/api/dm/send', {toId: botId, text});
        openDMModal(botId);
      } catch(e){ /* toast already shown */ }
    };

    sendBtn.onclick = sendMessage;
    input.onkeypress = (e) => { if(e.key === 'Enter') sendMessage(); };
  }

  function renderAttacks(){
    ensureBots();
    const playerNW = totalNetWorth();
    const minNW = playerNW * 0.5;
    const maxNW = playerNW * 2;

    document.getElementById('attackCity').textContent = state.location;
    document.getElementById('attackBombsOwned').textContent = Math.floor(state.bombs || 0);

    const allBots = state.bots || [];
    const botsInCity = allBots.filter(b => b.city === state.location);

    const validTargets = botsInCity.filter(b => {
      const botNW = botNetWorth(b);
      return botNW >= minNW && botNW <= maxNW;
    });

    const invalidTargets = botsInCity.filter(b => {
      const botNW = botNetWorth(b);
      return botNW < minNW || botNW > maxNW;
    });

    const validContainer = document.getElementById('validTargets');
    const invalidContainer = document.getElementById('invalidTargets');

    validContainer.classList.add('city-bots-grid');
    if(validTargets.length === 0){
      validContainer.innerHTML = '<div class="hint">No valid targets in your city.</div>';
    } else {
      const now = Date.now();
      const rosterIds = crewRosterIds();
      validContainer.innerHTML = validTargets.map(b => {
        const banUntil = (state.crewAttackBans || {})[b.id] || 0;
        const banned = now < banUntil;
        const banMinsLeft = banned ? Math.ceil((banUntil - now) / 60000) : 0;
        const inCrew = rosterIds.has(b.id);
        const blocked = banned || inCrew;
        return `
        <div class="bot-card">
          <div class="bot-card-top">
            <div class="bot-name">${b.isHuman ? `<span data-profile-id="${b.id}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(b.boss)}</span> <span style="color:var(--teal); font-size:0.7rem; font-weight:700;">🧑 REAL PLAYER</span>` : escapeHtml(b.boss)}</div>
          </div>
          <div style="font-size:0.8rem; color:var(--text-dim);">Net Worth: ${fmtMoney(botNetWorth(b))}</div>
          ${inCrew
            ? `<div style="font-size:0.8rem; color:var(--teal); text-align:center; padding:8px;">🤝 In your crew — can't be attacked</div>`
            : banned
            ? `<div style="font-size:0.8rem; color:var(--danger); text-align:center; padding:8px;">🛡️ Recently dropped from your crew — attackable again in ${banMinsLeft} min</div>`
            : `<button class="cta attack" data-attack-bot="${b.id}" ${state.thugs < 1 ? 'disabled' : ''}>⚔️ Attack — Send all thugs</button>`}
          ${!blocked && b.thugs === 0 ? `
            <div class="hint" style="text-align:center; margin:6px 0 4px;">Pick a factory type — you won't see what they actually have, and neither will you find out how many you hit. Costs ${BOMB_TURN_COST} turns even if they own none of it.</div>
            <div class="bomb-controls" style="display:flex; gap:6px;">
              <select data-bomb-factory="${b.id}" style="flex:1; min-width:0; background:var(--bg-2); border:1px solid var(--panel-line); color:var(--text); font-family:'IBM Plex Mono',monospace; font-size:0.78rem; padding:7px 6px; border-radius:6px; outline:none;">
                ${Object.entries(FACTORY_TYPE_LABELS).map(([type, label]) => `<option value="${type}">${label}</option>`).join('')}
              </select>
            </div>
            <button class="cta cta-sm" data-bomb-submit="${b.id}" style="background:var(--red); width:100%; margin-top:6px;" ${state.turns < BOMB_TURN_COST ? 'disabled' : ''}>💣 Bomb${state.turns < BOMB_TURN_COST ? ` (need ${BOMB_TURN_COST} turns)` : ''}</button>
            <div class="hint" style="text-align:center; margin:10px 0 4px;">Pick which cars to take — same deal, no numbers shown either way. Needs ${STEAL_CARS_THUGS_PER_CAR} thugs per car and costs ${STEAL_CARS_TURN_COST} turns even if they own none.</div>
            <div class="steal-car-controls" style="display:flex; gap:6px;">
              <select data-steal-car-type="${b.id}" style="flex:1; min-width:0; background:var(--bg-2); border:1px solid var(--panel-line); color:var(--text); font-family:'IBM Plex Mono',monospace; font-size:0.78rem; padding:7px 6px; border-radius:6px; outline:none;">
                ${Object.entries(CAR_TYPE_LABELS).map(([type, label]) => `<option value="${type}">${label}</option>`).join('')}
              </select>
            </div>
            <button class="cta cta-sm" data-steal-car-submit="${b.id}" style="background:var(--gold); width:100%; margin-top:6px;" ${(state.turns < STEAL_CARS_TURN_COST || state.thugs < STEAL_CARS_THUGS_PER_CAR) ? 'disabled' : ''}>🚗 Steal Cars${state.turns < STEAL_CARS_TURN_COST ? ` (need ${STEAL_CARS_TURN_COST} turns)` : (state.thugs < STEAL_CARS_THUGS_PER_CAR ? ` (need ${STEAL_CARS_THUGS_PER_CAR} thugs)` : '')}</button>` : ''}
          ${!blocked && b.thugs > 0 ? `<div style="font-size:0.8rem; color:var(--text-dim); text-align:center;">Defeat all their thugs to bomb factories or steal their cars</div>` : ''}
        </div>`;
      }).join('');
      validContainer.querySelectorAll('[data-attack-bot]').forEach(btn => {
        btn.addEventListener('click', () => fightBot(parseInt(btn.dataset.attackBot)));
      });
      validContainer.querySelectorAll('[data-bomb-submit]').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.dataset.bombSubmit;
          const select = validContainer.querySelector(`[data-bomb-factory="${id}"]`);
          bombBot(parseInt(id), select.value, null);
        });
      });
      validContainer.querySelectorAll('[data-steal-car-submit]').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.dataset.stealCarSubmit;
          const select = validContainer.querySelector(`[data-steal-car-type="${id}"]`);
          stealCars(parseInt(id), select.value, null);
        });
      });
      validContainer.querySelectorAll('[data-profile-id]').forEach(el => {
        el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
      });
    }

    if(invalidTargets.length === 0){
      invalidContainer.innerHTML = '';
    } else {
      invalidContainer.innerHTML = invalidTargets.map(b => {
        const botNW = botNetWorth(b);
        const reason = botNW < minNW ? '⬇️ Too weak' : '⬆️ Too strong';
        return `
          <div style="border:1px solid var(--panel-line); border-radius:8px; padding:12px; background:var(--panel); opacity:0.6;">
            <div style="display:flex; justify-content:space-between;">
              <div>
                <div>${b.isHuman ? `<span data-profile-id="${b.id}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(b.boss)}</span>` : escapeHtml(b.boss)}</div>
                <div style="font-size:0.8rem;">Net Worth: ${fmtMoney(botNW)}</div>
              </div>
              <div style="text-align:right;">${reason}</div>
            </div>
          </div>
        `;
      }).join('');
      invalidContainer.querySelectorAll('[data-profile-id]').forEach(el => {
        el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
      });
    }

    renderAttackFeed();
  }

  function renderAttackFeed(){
    const feedContainer = document.getElementById('attackFeedList');
    if(!feedContainer) return;
    const log = state.globalAttackLog || [];
    if(log.length === 0){
      feedContainer.innerHTML = '<div class="hint">No attacks yet — check back soon.</div>';
      return;
    }
    feedContainer.innerHTML = log.slice().reverse().slice(0, 30).map(e => `
      <div style="display:flex; align-items:center; gap:8px; padding:8px 10px; border:1px solid var(--panel-line); border-radius:8px; background:var(--panel); font-size:0.82rem;">
        <span style="flex-shrink:0;">${emblemInlineHtml(e.attackerEmblem)}</span>
        <span style="font-weight:700;">${escapeHtml(e.attacker)}</span>
        <span style="color:var(--red); flex-shrink:0;">⚔️</span>
        <span style="font-weight:700;">${escapeHtml(e.defender)}</span>
        <span style="flex-shrink:0;">${emblemInlineHtml(e.defenderEmblem)}</span>
        <span style="margin-left:auto; color:var(--text-dim); flex-shrink:0; white-space:nowrap;">${timeAgo(e.t)}</span>
      </div>
    `).join('');
  }

  function renderMessages(){
    ensureBots();
    const container = document.getElementById('conversationsList');

    // Get unique bot IDs from messages
    const botIds = new Set();
    (state.messages || []).forEach(m => {
      if(m.from === 'player') botIds.add(m.to);
      if(m.to === 'player') botIds.add(m.from);
    });

    if(botIds.size === 0){
      container.innerHTML = '<div class="hint">No messages yet. Send a DM to start a conversation!</div>';
      return;
    }

    const conversations = Array.from(botIds).map(botId => {
      const bot = state.bots.find(b => b.id === botId);
      if(!bot) return null;

      const messages = (state.messages || []).filter(m =>
        (m.from === 'player' && m.to === botId) || (m.from === botId && m.to === 'player')
      );

      const lastMessage = messages[messages.length - 1];
      const unreadCount = messages.filter(m => m.from === botId && !m.read).length;

      return {
        botId,
        botName: bot.boss,
        lastMessage: lastMessage ? `${lastMessage.kind === 'attack' ? '💥 ' : ''}${lastMessage.text}` : '',
        lastTime: lastMessage ? new Date(lastMessage.timestamp).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'}) : '',
        unreadCount,
        messageCount: messages.length,
      };
    }).filter(Boolean);

    container.innerHTML = conversations.map(conv => `
      <div style="border:2px solid var(--card-border); border-radius:8px; padding:12px; background:var(--card-bg); cursor:pointer; transition:all 0.2s;" class="msg-conv" data-msg-bot="${conv.botId}">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div style="font-weight:700; font-size:1rem;">${escapeHtml(conv.botName)}</div>
          <div style="font-size:0.8rem; color:var(--text-dim);">${conv.lastTime}</div>
        </div>
        <div style="color:var(--text-dim); font-size:0.9rem; margin-bottom:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          ${escapeHtml(conv.lastMessage)}
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:0.8rem; color:var(--text-dim);">${conv.messageCount} messages</span>
          ${conv.unreadCount > 0 ? `<span style="background:var(--hot); color:#fff; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;">${conv.unreadCount} new</span>` : ''}
        </div>
      </div>
    `).join('');

    container.querySelectorAll('.msg-conv').forEach(el => {
      el.addEventListener('click', () => openDMModal(parseInt(el.dataset.msgBot)));
      el.addEventListener('mouseenter', () => el.style.borderColor = 'var(--teal)');
      el.addEventListener('mouseleave', () => el.style.borderColor = 'var(--gold)');
    });
  }

  function renderSettings(){
    const toggle = document.getElementById('workResultsToggle');
    if(toggle) toggle.checked = state.showWorkResults;
    const tutorialToggle = document.getElementById('tutorialToggle');
    if(tutorialToggle) tutorialToggle.checked = state.showTutorial !== false;
    updatePushToggleBtn();
    const refInput = document.getElementById('referralLinkInput');
    if(refInput && currentUser) refInput.value = `${window.location.origin}/?ref=${currentUser.id}`;
    const pimpNameInput = document.getElementById('pimpNameInput');
    if(pimpNameInput && document.activeElement !== pimpNameInput){
      pimpNameInput.value = state.name || '';
    }
    const bioInput = document.getElementById('bioInput');
    if(bioInput && document.activeElement !== bioInput){
      bioInput.value = state.bio || '';
      updateBioCharCount();
    }
  }

  function updateBioCharCount(){
    const bioInput = document.getElementById('bioInput');
    const counter = document.getElementById('bioCharCount');
    if(bioInput && counter) counter.textContent = `${bioInput.value.length} / 200`;
  }

  // ---- Onboarding tutorial ----
  const TUTORIAL_STEPS = [
    {
      target: '.ts-stat.turns',
      title: '⏳ Welcome to the Streets',
      body: "You're building an empire, and everything takes energy. Actions cost Turns, which refill over time.",
    },
    {
      target: '.work-panel',
      title: '💼 Work the Block',
      body: "Let's make your first stack. Pick a location, set how many turns to spend, and hit the block. You'll earn cash and find workers.",
    },
    {
      target: '#hoeHappinessBlock',
      title: '👠 Hoe Happiness',
      body: "Good earner. But your workers need upkeep. Hoes need meds to stay happy, or they walk. Keep happiness above 40%.",
    },
    {
      target: '.ts-stat.thugs',
      title: '💪 Thug Morale',
      body: "The streets aren't safe. You need muscle. As you find thugs, buy them guns so they can defend your turf.",
    }
  ];

  let tutorialStep = 0;

  function openTutorial(){
    showPage('page-main');
    tutorialStep = 0;
    document.getElementById('tutorialOverlay').classList.add('show');
    renderTutorialStep();
    window.addEventListener('resize', renderTutorialStep);
  }

  function closeTutorial(){
    document.getElementById('tutorialOverlay').classList.remove('show');
    window.removeEventListener('resize', renderTutorialStep);
  }

  function renderTutorialStep(){
    const step = TUTORIAL_STEPS[tutorialStep];
    const highlight = document.getElementById('tutorialHighlight');
    const tooltip = document.getElementById('tutorialTooltip');
    const arrow = document.getElementById('tutorialArrow');

    document.getElementById('tutorialStepLabel').textContent = `Step ${tutorialStep + 1} of ${TUTORIAL_STEPS.length}`;
    document.getElementById('tutorialTitle').textContent = step.title;
    document.getElementById('tutorialBody').textContent = step.body;
    document.getElementById('tutorialBackBtn').style.visibility = tutorialStep === 0 ? 'hidden' : 'visible';
    document.getElementById('tutorialNextBtn').textContent = tutorialStep === TUTORIAL_STEPS.length - 1 ? 'Got it!' : 'Next →';

    const targetEl = step.target ? document.querySelector(step.target) : null;

    if(!targetEl){
      highlight.classList.add('center-mode');
      tooltip.classList.add('center-mode');
      arrow.style.display = 'none';
      return;
    }

    highlight.classList.remove('center-mode');
    tooltip.classList.remove('center-mode');
    arrow.style.display = 'block';

    targetEl.scrollIntoView({block: 'center', behavior: 'auto'});

    requestAnimationFrame(() => {
      const rect = targetEl.getBoundingClientRect();
      const pad = 6;
      highlight.style.top = (rect.top - pad) + 'px';
      highlight.style.left = (rect.left - pad) + 'px';
      highlight.style.width = (rect.width + pad * 2) + 'px';
      highlight.style.height = (rect.height + pad * 2) + 'px';

      const tooltipWidth = tooltip.offsetWidth || 300;
      const tooltipHeight = tooltip.offsetHeight || 160;
      const margin = 14;

      const placeBelow = (rect.bottom + margin + tooltipHeight) <= window.innerHeight;
      let top;
      if(placeBelow){
        top = rect.bottom + margin;
        arrow.className = 'tutorial-arrow arrow-up';
      } else {
        top = rect.top - margin - tooltipHeight;
        arrow.className = 'tutorial-arrow arrow-down';
      }
      top = Math.max(10, Math.min(top, window.innerHeight - tooltipHeight - 10));

      let left = rect.left + rect.width / 2 - tooltipWidth / 2;
      left = Math.max(10, Math.min(left, window.innerWidth - tooltipWidth - 10));

      tooltip.style.top = top + 'px';
      tooltip.style.left = left + 'px';

      const arrowLeft = Math.max(16, Math.min(rect.left + rect.width / 2 - left - 7, tooltipWidth - 30));
      arrow.style.left = arrowLeft + 'px';
    });
  }

  function maybeShowTutorial(){
    if(currentUser && state && state.showTutorial !== false){
      openTutorial();
    }
  }

  function renderCrewLeaderboard(){
    const roster = (state.crewRoster && state.crewRoster.members) || [];
    const name = document.getElementById('crewLBName');
    const membersEl = document.getElementById('crewLBMembers');
    const nw = document.getElementById('crewLBNetworth');
    const list = document.getElementById('crewLBList');

    if(!state.gang || roster.length === 0){
      if(name) name.textContent = 'No crew yet';
      if(membersEl) membersEl.textContent = '0';
      if(nw) nw.textContent = '£0';
      if(list) list.innerHTML = '<div class="hint">Create a crew name and invite members to see their combined power!</div>';
      return;
    }

    let crewTotal = 0;
    const crewMembers = roster.map(m => {
      // Use live local numbers for your own row so it doesn't lag a
      // server round-trip behind whatever you just did.
      const memberNw = m.isYou ? totalNetWorth() : m.netWorth;
      crewTotal += memberNw;
      return {
        name: m.name,
        nw: memberNw,
        isYou: !!m.isYou,
        cars: m.isYou ? (state.cadillacs || 0) : m.cars,
      };
    });

    name.textContent = state.gang;
    membersEl.textContent = crewMembers.length;
    nw.textContent = fmtMoney(crewTotal);

    // Sort by networth highest first
    crewMembers.sort((a, b) => b.nw - a.nw);

    list.innerHTML = crewMembers.map(m => `
      <div class="crew-lb-row ${m.isYou ? 'you' : ''}">
        <div style="flex:1;">
          <div class="crew-lb-member">${escapeHtml(m.name)}${m.isYou ? ' (You)' : ''}</div>
          ${!m.isYou ? `<div style="font-size:0.8rem; color:var(--text-dim); margin-top:4px;">🚗 ${Math.floor(m.cars)}</div>` : ''}
        </div>
        <div class="crew-lb-nw">${fmtMoney(m.nw)}</div>
      </div>
    `).join('');
  }

  function renderCrew(){
    ensureBots();
    if(!state.crewMembers) state.crewMembers = [];
    renderCrewEmblemPicker();

    const members = document.getElementById('crewMembers');
    const available = document.getElementById('crewAvailable');
    const subtitle = document.getElementById('crewSubtitle');
    const pendingPanel = document.getElementById('pendingInvitesPanel');
    const pendingList = document.getElementById('pendingInvitesList');
    const crewNameInput = document.getElementById('crewNameInput');
    const saveCrewNameBtn = document.getElementById('saveCrewNameBtn');

    if(!members || !available || !subtitle) return;

    const isMember = !!state.crewLeaderUserId;
    const alreadyAffiliated = !!state.gang;

    // Once you're in a crew (leader or member), creating a brand new one
    // is blocked - but leaders keep the ability to rename their own.
    if(crewNameInput && saveCrewNameBtn){
      const lockCreate = isMember;
      crewNameInput.disabled = lockCreate;
      saveCrewNameBtn.disabled = lockCreate;
      saveCrewNameBtn.style.opacity = lockCreate ? '0.4' : '1';
      saveCrewNameBtn.style.cursor = lockCreate ? 'not-allowed' : 'pointer';
      saveCrewNameBtn.title = lockCreate ? "You're a member of a crew — only its leader can rename it" : '';
    }

    const pending = state.pendingCrewInvites || [];
    if(pendingPanel && pendingList){
      if(pending.length === 0){
        pendingPanel.style.display = 'none';
      } else {
        pendingPanel.style.display = 'block';
        pendingList.innerHTML = pending.map(inv => `
          <div class="crew-card">
            <div class="crew-card-info">
              <div class="crew-card-name">${escapeHtml(inv.fromName)}</div>
              <div class="crew-card-gang">wants you to join "${escapeHtml(inv.fromGang)}"</div>
              ${alreadyAffiliated ? `<div class="hint" style="margin-top:4px;">You're already in a crew — leave it to accept this.</div>` : ''}
            </div>
            <div class="crew-card-action" style="display:flex; gap:8px;">
              <button class="cta gold" data-accept-invite="${inv.fromUserId}" ${alreadyAffiliated ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}>Accept</button>
              <button class="cta danger" data-decline-invite="${inv.fromUserId}">Decline</button>
            </div>
          </div>
        `).join('');
        pendingList.querySelectorAll('[data-accept-invite]:not(:disabled)').forEach(btn => {
          btn.addEventListener('click', () => acceptCrewInvite(parseInt(btn.dataset.acceptInvite)));
        });
        pendingList.querySelectorAll('[data-decline-invite]').forEach(btn => {
          btn.addEventListener('click', () => declineCrewInvite(parseInt(btn.dataset.declineInvite)));
        });
      }
    }

    if(!state.gang){
      members.innerHTML = '<div class="hint">🚨 You haven\'t created a crew name yet! Set one above to start recruiting.</div>';
      available.innerHTML = '<div class="hint">Create a crew name above to invite members.</div>';
      subtitle.textContent = '0 / 5 members';
      return;
    }

    if(isMember){
      subtitle.textContent = `Member of "${state.gang}"`;
      members.innerHTML = `<div class="hint">👤 You're a member of "${escapeHtml(state.gang)}", led by <b>${escapeHtml(state.crewLeaderName || '—')}</b>. Only the leader can invite, remove members, or set the emblem.</div>`;
      available.innerHTML = '';
      return;
    }

    subtitle.textContent = `${state.crewMembers.length} / 5 members`;

    if(state.crewMembers.length === 0){
      members.innerHTML = '<div class="hint">No crew members yet. Invite players from the list below!</div>';
    } else {
      members.innerHTML = state.crewMembers.map(m => {
        const bot = state.bots.find(b => b.id === m.botId);
        const isHuman = bot?.isHuman || m.botId >= 1000000;
        if(!bot){
          // Bot data hasn't loaded yet (or the member vanished from the
          // shared roster) - show the basic invite-time info rather than
          // a broken stat grid of undefineds.
          return `
            <div class="crew-card">
              <div class="crew-card-info">
                <div class="crew-card-id">${isHuman ? '🧑' : '#' + String(m.botId + 1).padStart(2, '0')}</div>
                <div class="crew-card-name">${escapeHtml(m.boss)}</div>
                <div class="crew-card-gang">"${escapeHtml(m.gang)}"</div>
              </div>
              <div class="crew-card-action">
                <button class="cta danger" data-remove="${m.botId}">Remove</button>
              </div>
            </div>
          `;
        }
        const nw = botNetWorth(bot);
        const guns = botTotalGuns(bot);
        const factories = botTotalFactories(bot);
        return `
          <div class="crew-card crew-member-card">
            <div class="crew-member-top">
              <div class="crew-card-info">
                <div class="crew-card-id">${isHuman ? '🧑' : '#' + String(m.botId + 1).padStart(2, '0')}</div>
                <div class="crew-card-name">${isHuman ? `<span data-profile-id="${m.botId}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(m.boss)}</span>` : escapeHtml(m.boss)}</div>
                <div class="crew-card-gang">"${escapeHtml(m.gang)}" · ${escapeHtml(bot.city || '—')}</div>
              </div>
              <div class="crew-card-action">
                <button class="cta danger" data-remove="${m.botId}">Remove</button>
              </div>
            </div>
            <div class="crew-member-stats">
              <div class="cms-tile"><div class="cms-label">Net Worth</div><div class="cms-val gold">${fmtMoney(nw)}</div></div>
              <div class="cms-tile"><div class="cms-label">Thugs</div><div class="cms-val">${bot.thugs || 0}</div><div class="cms-sub">${Math.round(bot.thugMorale || 0)}% morale</div></div>
              <div class="cms-tile"><div class="cms-label">Hoes</div><div class="cms-val">${bot.hoes || 0}</div><div class="cms-sub">${Math.round(bot.hoeMorale || 0)}% happy</div></div>
              <div class="cms-tile"><div class="cms-label">Guns</div><div class="cms-val">🔫 ${guns}</div></div>
              <div class="cms-tile"><div class="cms-label">Cars</div><div class="cms-val">🚗 ${Math.floor(bot.cadillacs || 0)}</div></div>
              <div class="cms-tile"><div class="cms-label">Factories</div><div class="cms-val">🏭 ${factories}</div></div>
            </div>
          </div>
        `;
      }).join('');
      members.querySelectorAll('[data-remove]').forEach(btn => {
        btn.addEventListener('click', () => removeFromCrew(parseInt(btn.dataset.remove)));
      });
      members.querySelectorAll('[data-profile-id]').forEach(el => {
        el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
      });
    }

    const availableBots = (state.bots || []).filter(b => !state.crewMembers.find(m => m.botId === b.id));
    if(availableBots.length === 0){
      available.innerHTML = '<div class="hint">All bots are in your crew or crew is full!</div>';
    } else {
      available.innerHTML = availableBots.map(b => `
        <div class="crew-card">
          <div class="crew-card-info">
            <div class="crew-card-id">${b.isHuman ? '🧑' : '#' + String(b.id + 1).padStart(2, '0')}</div>
            <div class="crew-card-name">${b.isHuman ? `<span data-profile-id="${b.id}" style="cursor:pointer; text-decoration:underline dotted;" title="View profile">${escapeHtml(b.boss)}</span> <span style="color:var(--teal); font-size:0.7rem;">REAL PLAYER</span>` : escapeHtml(b.boss)}</div>
            <div class="crew-card-gang">Currently: "${escapeHtml(b.gang || 'Unaffiliated')}"</div>
          </div>
          <div class="crew-card-action">
            <button class="cta gold" data-invite="${b.id}" ${state.crewMembers.length >= 5 ? 'disabled' : ''}>${b.isHuman ? 'Send Invite' : 'Invite'}</button>
          </div>
        </div>
      `).join('');
      available.querySelectorAll('[data-invite]').forEach(btn => {
        btn.addEventListener('click', () => inviteToCrewFromLeaderboard(parseInt(btn.dataset.invite)));
      });
      available.querySelectorAll('[data-profile-id]').forEach(el => {
        el.addEventListener('click', () => openProfile(parseInt(el.dataset.profileId)));
      });
    }
  }

  const THE_MINT_ROLE_ORDER = ['don', 'gunman', 'driver', 'bomber'];
  const THE_MINT_ROLE_LABELS = {don: 'The Don', gunman: 'Gunman', driver: 'Driver', bomber: 'Bomber'};

  function theMintRequirement(role){
    if(role === 'don') return {have: state.cash || 0, need: 250000000, unit: 'cash', text: n => `£${n.toLocaleString()}`};
    if(role === 'gunman'){
      const guns = state.guns || {};
      const have = (guns.pistol9mm || 0) + (guns.shotgun12gauge || 0) + (guns.ak47 || 0) + (guns.m249 || 0);
      return {have, need: 10000, unit: 'guns', text: n => `${n.toLocaleString()} guns`};
    }
    if(role === 'driver') return {have: state.cadillacs || 0, need: 300, unit: 'cars', text: n => `${n.toLocaleString()} cars`};
    return {have: state.bombs || 0, need: 500, unit: 'bombs', text: n => `${n.toLocaleString()} bombs`};
  }

  function renderTheMint(){
    const panel = document.getElementById('theMintPanel');
    const body = document.getElementById('theMintBody');
    const hint = document.getElementById('theMintHint');
    if(!panel || !body || !hint) return;
    panel.style.display = 'block';

    const roster = state.crewRoster || {};
    const job = roster.theJob;
    const cooldownUntil = roster.theJobCooldownUntil || 0;
    const now = Date.now();
    const myId = myUserId();
    const myRank = (state.rankInfo && state.rankInfo.level) || 1;
    const teaserText = 'One massive, once-a-day crew job: rob the Royal Mint gold vault for £1bn-£10bn. Needs a Don (rank 13, THE DON) who pays cash to plan it, plus a Gunman, Driver, and Bomber who each donate guns, cars, and bombs straight from their own stockpile. Once it fires, it takes a couple of minutes to actually go down.';

    // Always visible, even with no crew or too low a rank - it's meant to
    // be an aspirational "here's the endgame" teaser everyone can see, just
    // not everyone can act on yet.
    if(!state.gang){
      hint.textContent = teaserText;
      body.innerHTML = `<div class="hint">🔒 You need to be in a crew to attempt this. Form or join one from the Crew page first.</div>`;
      return;
    }

    if(!job){
      hint.textContent = teaserText;
      if(now < cooldownUntil){
        const hrs = Math.ceil((cooldownUntil - now) / (60 * 60 * 1000));
        body.innerHTML = `<div class="hint">Your crew just pulled a job — try again in ${hrs}h.</div>`;
      } else {
        body.innerHTML = `<button class="cta gold" id="startTheMintBtn" style="width:100%;">🏆 Plan The Mint</button>`;
        document.getElementById('startTheMintBtn').addEventListener('click', startTheMint);
      }
      return;
    }

    if(job.executesAt){
      const remaining = Math.max(0, job.executesAt - now);
      const mins = Math.floor(remaining / 60000);
      const secs = Math.floor((remaining % 60000) / 1000);
      hint.innerHTML = `<b style="color:var(--gold);">£${job.prize.toLocaleString()}</b> on the line. All 4 roles are in — The Job is underway.`;
      body.innerHTML = `<div class="hint" style="font-size:1rem;">⏳ Results in ${mins}:${String(secs).padStart(2, '0')}...</div>`;
      return;
    }

    hint.innerHTML = `<b style="color:var(--gold);">£${job.prize.toLocaleString()}</b> up for grabs — started by ${escapeHtml(job.startedByName)}. Once all 4 roles are filled, it takes a couple of minutes to go down (70% success chance — fail and every donation is lost).`;

    const isDon = job.roles.don.userId === myId;
    const rows = THE_MINT_ROLE_ORDER.map(role => {
      const r = job.roles[role];
      const label = THE_MINT_ROLE_LABELS[role];
      const pct = job.splits[role];
      const req = theMintRequirement(role);
      let statusHtml;
      if(r.userId != null){
        statusHtml = `<b style="color:var(--teal);">${escapeHtml(r.name)}</b>${r.userId === myId ? ' (you)' : ''}`;
      } else {
        const canClaimDon = role !== 'don' || myRank >= 13;
        const canAfford = req.have >= req.need;
        let actionHtml;
        if(!canClaimDon){
          actionHtml = `<span class="hint" style="font-size:0.7rem;">Needs rank 13 (THE DON)</span>`;
        } else if(!canAfford){
          actionHtml = `<span class="hint" style="font-size:0.7rem;">Need ${req.text(req.need)} (you have ${req.text(req.have)})</span>`;
        } else {
          actionHtml = `<button class="cta gold" data-claim-role="${role}" style="width:100%; font-size:0.72rem; padding:6px;">Donate ${req.text(req.need)} — take role</button>`;
        }
        statusHtml = `<span style="color:var(--text-dim);">Open — needs ${req.text(req.need)}</span>
          <div style="margin-top:6px;">${actionHtml}</div>`;
      }
      return `
        <div class="panel" style="margin-bottom:8px; padding:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <b>${label}</b>
            <span style="color:var(--gold);">${pct}%</span>
          </div>
          <div style="margin-top:6px; font-size:0.85rem;">${statusHtml}</div>
        </div>
      `;
    }).join('');

    let splitEditor = '';
    if(isDon){
      splitEditor = `
        <div class="panel" style="margin-top:10px; padding:10px;">
          <div style="font-size:0.85rem; margin-bottom:8px;">You're the Don — set the split (must add up to 100):</div>
          <div style="display:flex; gap:6px; flex-wrap:wrap;">
            ${THE_MINT_ROLE_ORDER.map(role => `
              <label style="display:flex; flex-direction:column; font-size:0.7rem; color:var(--text-dim); gap:2px;">
                ${THE_MINT_ROLE_LABELS[role]}
                <input type="number" min="0" max="100" id="mintSplit_${role}" value="${job.splits[role]}" style="width:60px; padding:4px; background:var(--bg-2); border:1px solid var(--panel-line); color:var(--text); border-radius:4px;">
              </label>
            `).join('')}
          </div>
          <button class="cta gold" id="saveMintSplitBtn" style="width:100%; margin-top:8px;">Save Split</button>
        </div>
      `;
    }

    body.innerHTML = rows + splitEditor;

    body.querySelectorAll('[data-claim-role]').forEach(btn => {
      btn.addEventListener('click', () => claimMintRole(btn.dataset.claimRole));
    });
    if(isDon){
      document.getElementById('saveMintSplitBtn').addEventListener('click', saveMintSplit);
    }
  }

  async function startTheMint(){
    try{
      await apiCall('/api/thejob/start', {});
      showToast('🏆 The Mint job is on! Fill all 4 roles to pull it off.');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function claimMintRole(role){
    try{
      const r = await apiCall('/api/thejob/claim', {role});
      if(r && r.result && r.result.executing){
        showToast('🏆 All 4 roles are filled — The Job is underway!');
      } else {
        showToast('Role taken!');
      }
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function saveMintSplit(){
    const splits = {};
    THE_MINT_ROLE_ORDER.forEach(role => {
      splits[role] = parseInt(document.getElementById(`mintSplit_${role}`).value) || 0;
    });
    try{
      await apiCall('/api/thejob/split', {splits});
      showToast('Split updated.');
      render();
    } catch(e){ /* toast already shown */ }
  }

  async function resetGame(){
    if(!confirm('Reset your entire empire? This cannot be undone.')) return;
    try{
      await apiCall('/api/settings/reset');
      render();
      showToast('Empire reset.');
    } catch(e){ /* toast already shown */ }
  }

  // ---- Turn regen ticking ----
  // All actual regen/production/market math now happens
  // server-side (game_engine.apply_catchup). This function only refreshes
  // on-screen countdowns from the last-synced `state` every second, and a
  // separate slower interval (syncState, see below) periodically re-pulls
  // the authoritative state from the server so turns/factories/bots that
  // ticked over server-side show up without the player having to act.
  function tickRegen(){
    const now = Date.now();

    // Market drift display-only countdown (actual drift computed server-side)
    const bmPage = document.getElementById('page-blackmarket');
    if(bmPage && bmPage.classList.contains('active')){
      const marketSub = document.querySelectorAll('.market-sub');
      if(marketSub.length){
        const nextMs = MARKET_MS - ((now - (state.lastMarketUpdate||now)) % MARKET_MS);
        const nextMins = Math.max(0, Math.ceil(nextMs / 60000));
        marketSub.forEach(el => el.textContent = `next move in ~${nextMins} min`);
      }
    }

    // Bribe status
    updateBribeUI();
    updateLayLowUI();

    // Turn timer
    const remainder = REGEN_MS - ((now - state.lastRegen) % REGEN_MS);
    const mins = Math.floor(remainder / 60000);
    const secs = Math.floor((remainder % 60000) / 1000);
    document.getElementById('turnTimer').textContent =
      state.turns >= state.maxTurns ? 'turns full' : `next in ${mins}:${secs.toString().padStart(2,'0')}`;

    // Factory timer
    const factoryRemainder = FACTORY_MS - ((now - (state.lastFactoryRun || now)) % FACTORY_MS);
    const fMins = Math.floor(factoryRemainder / 60000);
    const fSecs = Math.floor((factoryRemainder % 60000) / 1000);
    const timerEl = document.getElementById('factoryTimer');
    if(timerEl){
      const f = state.factories || {medical:0,gun:0,car:0,drug:0,explosive:0,counterfeit:0,gym:0,warehouse:0};
      const hasFactories = f.medical > 0 || f.gun > 0 || f.car > 0 || (f.drug||0) > 0 || f.explosive > 0 || f.counterfeit > 0 || (f.gym||0) > 0;
      timerEl.textContent = hasFactories
        ? `Next factory run in ${fMins}:${fSecs.toString().padStart(2,'0')}`
        : 'No factories owned yet';
    }
  }

  async function buyFactory(type){
    const suffix = FACTORY_ID_SUFFIX[type];
    const qtyInput = document.getElementById(`buy${suffix}Qty`);
    const qty = Math.max(1, parseInt(qtyInput?.value) || 1);
    try{
      const data = await apiCall('/api/factory/buy', {type, qty});
      showToast(`Bought ${data.result.qty} ${type} factor${data.result.qty === 1 ? 'y' : 'ies'} for ${fmtMoney(data.result.cost)}.`);
      render(); renderRealEstate();
    } catch(e){ /* toast already shown */ }
  }

  async function sellFactory(type, qty){
    try{
      const data = await apiCall('/api/factory/sell', {type, qty});
      showToast(`Sold ${data.result.qty} ${type} factor${data.result.qty === 1 ? 'y' : 'ies'} for ${fmtMoney(data.result.payout)}.`);
      render(); renderRealEstate();
    } catch(e){ /* toast already shown */ }
  }

  // Must match WAREHOUSE_BASE_CAPACITY / WAREHOUSE_CAPACITY_PER_UNIT in game_engine.py.


  const FACTORY_ID_SUFFIX = {medical: 'Medical', gun: 'Gun', car: 'Car', drug: 'Drug', explosive: 'Explosive', counterfeit: 'Counterfeit', gym: 'Gym', warehouse: 'Warehouse'};
  // Must match FACTORY_UNLOCK_RANK / RANKS in game_engine.py - Real Estate is
  // a progression ladder, not a shopping list you can max out from Rank 1.

  const RANK_NAMES = ['', 'Junkie', 'Street Rat', 'Foot Soldier', 'Associate', 'Gang Member', 'Gang Leader', 'Mob Boss', 'Underboss', 'Consigliere', 'Capo', 'Boss of Bosses', 'Kingpin', 'THE DON'];

  function isFactoryUnlocked(type){
    return (state.rankInfo?.level || 1) >= FACTORY_UNLOCK_RANK[type];
  }

  function updateSellFactoryLabel(type){
    const suffix = FACTORY_ID_SUFFIX[type];
    const slider = document.getElementById(`sell${suffix}Slider`);
    const label = document.getElementById(`sell${suffix}QtyLabel`);
    const btn = document.getElementById(`sell${suffix}Btn`);
    if(!slider || !label || !btn) return;
    const qty = parseInt(slider.value) || 0;
    label.textContent = qty;
    const payout = Math.round(FACTORY_SELL_PRICES[type] * qty);
    btn.textContent = `Sell ${qty} — ${fmtMoney(payout)}`;
    btn.disabled = qty < 1;
  }

  function setBuyQtyMax(type){
    const suffix = FACTORY_ID_SUFFIX[type];
    const input = document.getElementById(`buy${suffix}Qty`);
    if(!input || input.disabled) return;
    const affordable = Math.floor((state.cash || 0) / FACTORY_COSTS[type]);
    input.value = Math.max(1, affordable);
    updateBuyFactoryLabel(type);
  }

  function updateBuyFactoryLabel(type){
    const suffix = FACTORY_ID_SUFFIX[type];
    const input = document.getElementById(`buy${suffix}Qty`);
    const label = document.getElementById(`buy${suffix}QtyLabel`);
    const btn = document.getElementById(`buy${suffix}Btn`);
    const maxBtn = document.getElementById(`buy${suffix}MaxBtn`);
    if(!input || !label || !btn) return;
    if(!isFactoryUnlocked(type)){
      const requiredRank = FACTORY_UNLOCK_RANK[type];
      label.textContent = '—';
      btn.textContent = `🔒 Unlocks at Rank ${requiredRank} (${RANK_NAMES[requiredRank]})`;
      btn.disabled = true;
      input.disabled = true;
      if(maxBtn) maxBtn.disabled = true;
      return;
    }
    input.disabled = false;
    if(maxBtn) maxBtn.disabled = false;
    const qty = Math.max(1, parseInt(input.value) || 1);
    label.textContent = qty;
    const cost = FACTORY_COSTS[type] * qty;
    btn.textContent = `Buy ${qty} — ${fmtMoney(cost)}`;
    btn.disabled = state.cash < cost;
  }

  function setupSellSlider(type, owned){
    const suffix = FACTORY_ID_SUFFIX[type];
    const slider = document.getElementById(`sell${suffix}Slider`);
    if(!slider) return;
    slider.max = owned;
    if(parseInt(slider.value) > owned) slider.value = owned;
    updateSellFactoryLabel(type);
  }

  async function setCarFactoryRatio(pct){
    try{
      await apiCall('/api/factory/carratio', {ratio: pct});
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function sellAllCadillacs(){
    try{
      const data = await apiCall('/api/cadillacs/sellall', {});
      showToast(`Sold ${data.result.qty} cadillacs for ${fmtMoney(data.result.payout)}!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function sellAllMeds(){
    try{
      const data = await apiCall('/api/meds/sellall', {});
      showToast(`Sold ${data.result.qty} safety kits for ${fmtMoney(data.result.payout)}!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function sellAllCokeDealer(){
    try{
      const data = await apiCall('/api/cocaine/sellall', {});
      showToast(`Sold ${data.result.qty} cocaine for ${fmtMoney(data.result.payout)}!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function sellCokeOverseas(){
    try{
      const data = await apiCall('/api/cocaine/sellall/overseas', {});
      if(data.result.success){
        showToast(`✅ Shipment cleared customs! Made ${fmtMoney(data.result.payout)}!`);
      } else {
        showToast(`🚨 Busted at customs! Lost ${data.result.qty} cocaine for nothing.`);
      }
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function washFakeMoney(){
    try{
      const data = await apiCall('/api/fakemoney/wash', {});
      showToast(`Washed ${fmtMoney(data.result.qty)} fake money for ${fmtMoney(data.result.payout)} clean cash!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function washFakeMoneyOverseas(){
    try{
      const data = await apiCall('/api/fakemoney/wash/overseas', {});
      if(data.result.success){
        showToast(`✅ Offshore accounts cleared! Laundered into ${fmtMoney(data.result.payout)}!`);
      } else {
        showToast(`🚨 FBI seized the transfer! Lost ${fmtMoney(data.result.qty)} fake money for nothing.`);
      }
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  async function sellAllArmoredTrucks(){
    try{
      const data = await apiCall('/api/trucks/sellall', {});
      showToast(`Sold ${data.result.qty} armored trucks for ${fmtMoney(data.result.payout)}!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  const GUN_SELL_LABELS = {pistol9mm:'9mm', shotgun12gauge:'Shotguns', ak47:'AKs', m249:'M249s'};

  async function sellAllGuns(type){
    try{
      const data = await apiCall('/api/guns/sellall', {type});
      showToast(`Sold ${data.result.qty} ${GUN_SELL_LABELS[type]} for ${fmtMoney(data.result.payout)}!`);
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  function renderProduction(){
    const f = state.factories || {medical:0, gun:0, car:0, drug:0, explosive:0, counterfeit:0, gym:0, warehouse:0};

    const storageCap = WAREHOUSE_BASE_CAPACITY + (f.warehouse || 0) * WAREHOUSE_CAPACITY_PER_UNIT;
    const totalDrugs = Object.values(state.drugs || {}).reduce((a, b) => a + b, 0);
    const totalGuns = Object.values(state.guns || {}).reduce((a, b) => a + b, 0);
    const totalCars = (state.cadillacs || 0) + (state.armoredTrucks || 0);
    const storageRows = [
      {label: '❄️ Drugs', total: totalDrugs},
      {label: '🏭 Guns', total: totalGuns},
      {label: '🚗 Cars', total: totalCars},
    ];
    document.getElementById('storageCapacityGrid').innerHTML = storageRows.map(row => {
      const exposed = Math.max(0, row.total - storageCap);
      const color = exposed > 0 ? 'var(--danger)' : 'var(--text-dim)';
      return `
        <div style="padding:10px; background:var(--bg-2); border-radius:6px;">
          <div style="font-size:0.85rem; color:var(--text-dim);">${row.label}</div>
          <div style="font-weight:700;">${Math.floor(row.total).toLocaleString('en-GB')} / ${storageCap.toLocaleString('en-GB')}</div>
          ${exposed > 0 ? `<div style="font-size:0.78rem; color:${color};">⚠️ ${Math.floor(exposed).toLocaleString('en-GB')} exposed</div>` : `<div style="font-size:0.78rem; color:${color};">safely stored</div>`}
        </div>`;
    }).join('');

    document.getElementById('prodMedicalOwned').textContent = f.medical;
    document.getElementById('prodGunOwned').textContent = f.gun;
    document.getElementById('prodCarOwned').textContent = f.car;
    document.getElementById('prodDrugOwned').textContent = f.drug || 0;
    document.getElementById('prodDrugOutput').textContent = `${((f.drug || 0) * DRUG_FACTORY_RATE).toLocaleString('en-GB')} Cocaine / 30 mins`;

    const cokeStock = Math.floor(state.drugs?.coke || 0);
    document.getElementById('prodCokeStock').textContent = cokeStock.toLocaleString('en-GB');
    const dealerPrice = getDealerPrice(state.location, 'coke', true);
    const overseasPrice = Math.round(dealerPrice * 1.35);
    document.getElementById('prodCokeDealerPrice').textContent = fmtMoney(dealerPrice);
    document.getElementById('prodCokeOverseasPrice').textContent = fmtMoney(overseasPrice);
    const dealerBtn = document.getElementById('sellAllCokeDealerBtn');
    const overseasBtn = document.getElementById('sellOverseasCokeBtn');
    dealerBtn.disabled = cokeStock < 1;
    overseasBtn.disabled = cokeStock < 1;
    dealerBtn.textContent = cokeStock > 0 ? `Sell All (${fmtMoney(cokeStock * dealerPrice)})` : 'Sell All (Dealer)';
    overseasBtn.textContent = cokeStock > 0 ? `Sell Overseas (${fmtMoney(cokeStock * overseasPrice)})` : 'Sell Overseas';
    document.getElementById('prodExplosiveOwned').textContent = f.explosive;
    document.getElementById('prodExplosiveOutput').textContent = `${((f.explosive || 0) * EXPLOSIVE_BOMB_RATE).toLocaleString('en-GB')} Bombs / 30 mins`;
    document.getElementById('prodBombsStock').textContent = Math.floor(state.bombs || 0).toLocaleString('en-GB');
    document.getElementById('prodCounterfeitOwned').textContent = f.counterfeit || 0;
    document.getElementById('prodCounterfeitOutput').textContent = `${fmtMoney((f.counterfeit || 0) * COUNTERFEIT_CASH_RATE)} / 30 mins`;
    const fakeMoney = Math.floor(state.fakeMoney || 0);
    document.getElementById('prodFakeMoneyStock').textContent = fmtMoney(fakeMoney);
    
    const washLocalBtn = document.getElementById('washFakeMoneyBtn');
    const washOverseasBtn = document.getElementById('washFakeMoneyOverseasBtn');
    washLocalBtn.disabled = fakeMoney < 1;
    washOverseasBtn.disabled = fakeMoney < 1;
    washLocalBtn.textContent = fakeMoney > 0 ? `Wash Locally (${fmtMoney(fakeMoney)})` : 'Wash Locally';
    washOverseasBtn.textContent = fakeMoney > 0 ? `Wash Offshore (${fmtMoney(Math.round(fakeMoney * 1.9))})` : 'Wash Offshore';
    document.getElementById('prodGymOwned').textContent = f.gym || 0;
    document.getElementById('prodGymOutput').textContent = `${((f.gym || 0) * GYM_THUG_RATE).toLocaleString('en-GB')} Thugs / 30 mins`;
    document.getElementById('prodThugsStock').textContent = Math.floor(state.thugs || 0).toLocaleString('en-GB');

    const medsItem = BLACKMARKET_ITEMS.find(i => i.key === 'meds');
    const medsPrice = currentPrice(medsItem);
    document.getElementById('prodMedsPrice').textContent = fmtMoney(medsPrice);
    const medsOwned = Math.floor(state.medsStock || 0);
    document.getElementById('prodMedsStock').textContent = medsOwned;
    const sellMedsBtn = document.getElementById('sellAllMedsBtn');
    sellMedsBtn.disabled = medsOwned < 1;
    sellMedsBtn.textContent = medsOwned > 0 ? `Sell All Meds (${fmtMoney(medsOwned * medsPrice)})` : 'Sell All Meds';

    document.getElementById('prodCadillacsOwned').textContent = Math.floor(state.cadillacs || 0);
    document.getElementById('prodArmoredOwned').textContent = Math.floor(state.armoredTrucks || 0);

    document.getElementById('prodPistolOwned').textContent = Math.floor(state.guns?.pistol9mm || 0);
    document.getElementById('prodShotgunOwned').textContent = Math.floor(state.guns?.shotgun12gauge || 0);
    document.getElementById('prodAkOwned').textContent = Math.floor(state.guns?.ak47 || 0);
    document.getElementById('prodM249Owned').textContent = Math.floor(state.guns?.m249 || 0);

    const gunRatio = state.gunFactoryRatio ?? 0.0;
    const gunSlider = document.getElementById('gunRatioSlider');
    if(document.activeElement !== gunSlider){
      gunSlider.value = Math.round(gunRatio * 100);
    }
    updateGunMixLabel(parseInt(gunSlider.value));

    updateGunSellRow('pistol9mm', 'prodPistolPrice', 'sellAllPistolsBtn', '9mm');
    updateGunSellRow('shotgun12gauge', 'prodShotgunPrice', 'sellAllShotgunsBtn', 'Shotguns');
    updateGunSellRow('ak47', 'prodAkPrice', 'sellAllAksBtn', 'AKs');
    updateGunSellRow('m249', 'prodM249Price', 'sellAllM249sBtn', 'M249s');

    const ratio = state.carFactoryRatio ?? 1.0;
    const slider = document.getElementById('carRatioSlider');
    if(document.activeElement !== slider){
      slider.value = Math.round(ratio * 100);
    }
    updateCarMixLabel(parseInt(slider.value));

    const cadillacItem = BLACKMARKET_ITEMS.find(i => i.key === 'cars');
    const price = currentPrice(cadillacItem);
    document.getElementById('prodCadillacPrice').textContent = fmtMoney(price);

    const sellBtn = document.getElementById('sellAllCadillacsBtn');
    const owned = Math.floor(state.cadillacs || 0);
    sellBtn.disabled = owned < 1;
    sellBtn.textContent = owned > 0 ? `Sell All Cadillacs (${fmtMoney(owned * price)})` : 'Sell All Cadillacs';

    const truckItem = BLACKMARKET_ITEMS.find(i => i.key === 'trucks');
    const truckPrice = currentPrice(truckItem);
    document.getElementById('prodTruckPrice').textContent = fmtMoney(truckPrice);
    const sellTrucksBtn = document.getElementById('sellAllTrucksBtn');
    const trucksOwned = Math.floor(state.armoredTrucks || 0);
    sellTrucksBtn.disabled = trucksOwned < 1;
    sellTrucksBtn.textContent = trucksOwned > 0 ? `Sell All Armored Trucks (${fmtMoney(trucksOwned * truckPrice)})` : 'Sell All Armored Trucks';
  }

  function updateCarMixLabel(sliderVal){
    const rates = carFactoryOutputRates(sliderVal / 100);
    const owned = (state.factories && state.factories.car) || 0;
    const totalCadillacs = Math.round(rates.cadillacRate * owned);
    const totalArmored = Math.round(rates.armoredRate * owned);
    document.getElementById('prodCarMixLabel').textContent =
      `${Math.round(rates.cadillacRate)} Cadillacs / ${Math.round(rates.armoredRate)} Armored Trucks per factory`
      + (owned > 0 ? ` — Total: ${totalCadillacs} Cadillacs / ${totalArmored} Armored Trucks / 30 mins` : '');
  }

  function updateGunMixLabel(sliderVal){
    const rates = gunFactoryOutputRates(sliderVal / 100);
    const owned = (state.factories && state.factories.gun) || 0;
    const totalPistol = Math.round(rates.pistolRate * owned);
    const totalShotgun = Math.round(rates.shotgunRate * owned);
    const totalAk = Math.round(rates.akRate * owned);
    const totalM249 = Math.round(rates.m249Rate * owned);
    document.getElementById('prodGunMixLabel').textContent =
      `${Math.round(rates.pistolRate)} 9mm / ${Math.round(rates.shotgunRate)} Shotguns / ${Math.round(rates.akRate)} AKs / ${Math.round(rates.m249Rate)} M249s per factory`
      + (owned > 0 ? ` — Total: ${totalPistol} 9mm / ${totalShotgun} Shotguns / ${totalAk} AKs / ${totalM249} M249s / 30 mins` : '');
  }

  function updateGunSellRow(gunKey, priceElId, btnId, label){
    const item = BLACKMARKET_ITEMS.find(i => i.key === gunKey);
    const price = currentPrice(item);
    document.getElementById(priceElId).textContent = fmtMoney(price);
    const owned = Math.floor(state.guns?.[gunKey] || 0);
    const btn = document.getElementById(btnId);
    btn.disabled = owned < 1;
    btn.textContent = owned > 0 ? `Sell All ${label} (${fmtMoney(owned * price)})` : `Sell All ${label}`;
  }

  async function setGunFactoryRatio(pct){
    try{
      await apiCall('/api/factory/gunratio', {ratio: pct});
      render(); renderProduction();
    } catch(e){ /* toast already shown */ }
  }

  function renderRealEstate(){
    const f = state.factories || {medical:0, gun:0, car:0, drug:0, explosive:0, counterfeit:0, gym:0, warehouse:0};
    document.getElementById('ownedMedical').textContent = f.medical;
    document.getElementById('ownedGun').textContent = f.gun;
    document.getElementById('ownedCar').textContent = f.car;
    document.getElementById('ownedDrug').textContent = f.drug || 0;
    document.getElementById('ownedExplosive').textContent = f.explosive;
    document.getElementById('ownedCounterfeit').textContent = f.counterfeit;
    document.getElementById('ownedGym').textContent = f.gym || 0;
    document.getElementById('ownedWarehouse').textContent = f.warehouse || 0;
    document.getElementById('bombsOwned').textContent = state.bombs;
    updateBuyFactoryLabel('medical');
    updateBuyFactoryLabel('gun');
    updateBuyFactoryLabel('car');
    updateBuyFactoryLabel('drug');
    updateBuyFactoryLabel('explosive');
    updateBuyFactoryLabel('counterfeit');
    updateBuyFactoryLabel('gym');
    updateBuyFactoryLabel('warehouse');
    Object.keys(FACTORY_UNLOCK_RANK).forEach(type => {
      const card = document.querySelector(`[data-factory-card="${type}"]`);
      if(card) card.classList.toggle('locked', !isFactoryUnlocked(type));
    });
    ['medical', 'gun', 'car', 'drug', 'explosive', 'counterfeit', 'gym', 'warehouse'].forEach(type => {
      const buyPriceEl = document.getElementById(`buyPrice_${type}`);
      const sellPriceEl = document.getElementById(`sellPrice_${type}`);
      if(buyPriceEl) buyPriceEl.textContent = fmtMoney(FACTORY_COSTS[type] || 0);
      if(sellPriceEl) sellPriceEl.textContent = fmtMoney(FACTORY_SELL_PRICES[type] || 0);
    });
    setupSellSlider('medical', f.medical);
    setupSellSlider('gun', f.gun);
    setupSellSlider('car', f.car);
    setupSellSlider('drug', f.drug || 0);
    setupSellSlider('explosive', f.explosive || 0);
    setupSellSlider('counterfeit', f.counterfeit);
    setupSellSlider('gym', f.gym || 0);
    setupSellSlider('warehouse', f.warehouse || 0);
  }

  function fmtHM(ms){
    const totalMin = Math.max(0, Math.ceil(ms / 60000));
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  function renderHeistPage(){
    const jobs = {shop: HEIST_JOBS.shop, jewellery: HEIST_JOBS.jewellery, bank: HEIST_JOBS.bank};
    const btns = {shop:'doShopBtn', jewellery:'doJewBtn', bank:'doBankBtn'};
    const cashSpans = {shop:'shopCash', jewellery:'jewCash', bank:'bankCash'};
    const nw = totalNetWorth();
    const cooldownRemaining = (HEIST_JOB_COOLDOWN_HOURS * 3600000) - (Date.now() - (state.lastJobHeist || 0));
    const onCooldown = cooldownRemaining > 0;
    Object.entries(jobs).forEach(([id, job]) => {
      const btn = document.getElementById(btns[id]);
      const hasThugs = state.thugs >= job.minThugs;
      const hasTurns = state.turns >= job.turnCost;
      btn.disabled = !(hasThugs && hasTurns) || onCooldown;
      if(onCooldown){
        btn.textContent = `On cooldown — ${fmtHM(cooldownRemaining)}`;
      } else if(!hasThugs){
        btn.textContent = `Need ${job.minThugs} thugs (you have ${state.thugs})`;
      } else if(!hasTurns){
        btn.textContent = `Need ${job.turnCost} turns (you have ${state.turns})`;
      } else {
        btn.textContent = 'Send the crew in';
      }

      const lo = Math.max(job.minCash, Math.round(nw * job.netWorthPct.min));
      const hi = Math.max(job.maxCash, Math.round(nw * job.netWorthPct.max));
      document.getElementById(cashSpans[id]).textContent = `${fmtMoney(lo)} – ${fmtMoney(hi)}`;
    });

    const casinoJob = CASINO_JOB;
    const dashRoster = (state.crewRoster && state.crewRoster.members) || [];
    const crewNetWorth = nw + dashRoster.reduce((sum, m) => sum + (m.isYou ? 0 : m.netWorth), 0);
    const casinoLo = Math.max(casinoJob.minCash, Math.round(crewNetWorth * casinoJob.netWorthPct.min));
    const casinoHi = Math.max(casinoJob.maxCash, Math.round(crewNetWorth * casinoJob.netWorthPct.max));
    const casinoCashEl = document.getElementById('casinoCash');
    if(casinoCashEl) casinoCashEl.textContent = `${fmtMoney(casinoLo)} – ${fmtMoney(casinoHi)}`;

    renderTheMint();
  }

  // ---- Page navigation ----
  function showPage(id){
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    document.querySelectorAll('.sidebar-link').forEach(l => l.classList.toggle('active', l.dataset.page === id));
    document.body.classList.toggle('home-active', id === 'page-main');
    window.scrollTo({top:0, behavior:'smooth'});
  }

  function renderDealer(){
    const city = state.location || 'London';
    document.getElementById('dealerCity').textContent = `${city} dealer · Prices change every 10 minutes`;

    const container = document.getElementById('dealerDrugs');
    container.innerHTML = DOPE_DEALER_DRUGS.map(drug => {
      const have = state.drugs[drug.id] || 0;
      const buyPrice = getDealerPrice(city, drug.id, false);
      const sellPrice = getDealerPrice(city, drug.id, true);
      const boughtKey = `${city}_${drug.id}_bought`;
      const alreadyBought = state.dealerBoughtToday[boughtKey] || 0;
      const paidPrice = state.drugsPaidPrice[drug.id];

      return `
        <div style="border:1px solid var(--panel-line); border-radius:8px; padding:12px; background:var(--panel);">
          <div style="font-size:2rem; text-align:center; margin-bottom:8px;">${drug.icon}</div>
          <div style="font-weight:700; text-align:center; margin-bottom:8px;">${drug.name}</div>
          <div style="font-size:0.8rem; color:var(--text-dim); margin-bottom:8px;">Have: <b>${have}</b></div>
          ${paidPrice ? `<div style="font-size:0.75rem; color:var(--gold); margin-bottom:4px;">Bought for: ${fmtMoney(paidPrice)}</div>` : ''}
          <div style="font-size:0.8rem; color:var(--teal); margin-bottom:4px;">Buy: ${fmtMoney(buyPrice)}</div>
          <div style="font-size:0.75rem; color:var(--text-dim); margin-bottom:8px;">Today: ${alreadyBought}/100</div>
          <input type="number" id="buy_${drug.id}" min="1" max="100" value="1" style="width:100%; margin-bottom:6px; padding:4px; background:var(--bg); border:1px solid var(--panel-line); color:var(--text); border-radius:4px;">
          <button class="cta cta-buy dealer-buy-btn" style="width:100%; margin-bottom:8px;" data-drug="${drug.id}">Buy</button>
          <div style="font-size:0.8rem; color:var(--gold); margin-bottom:4px;">Sell: ${fmtMoney(sellPrice)}</div>
          <input type="number" id="sell_${drug.id}" min="1" max="${have}" value="1" style="width:100%; margin-bottom:6px; padding:4px; background:var(--bg); border:1px solid var(--panel-line); color:var(--text); border-radius:4px;">
          <button class="cta cta-sell dealer-sell-btn" style="width:100%;" data-drug="${drug.id}">Sell</button>
        </div>
      `;
    }).join('');

    // Wire up buy/sell buttons
    document.querySelectorAll('.dealer-buy-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const drugId = e.target.dataset.drug;
        const qty = parseInt(document.getElementById(`buy_${drugId}`).value) || 1;
        buyDrugs(drugId, qty);
      });
    });

    document.querySelectorAll('.dealer-sell-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const drugId = e.target.dataset.drug;
        const qty = parseInt(document.getElementById(`sell_${drugId}`).value) || 1;
        sellDrugs(drugId, qty);
      });
    });
  }

  const PAGE_RENDERERS = {
    'page-heist': renderHeistPage,
    'page-realestate': renderRealEstate,
    'page-production': renderProduction,
    'page-blackmarket': renderBlackMarket,
    'page-dealer': renderDealer,
    'page-travel': renderLocation,
    'page-crew': renderCrew,
    'page-crew-leaderboard': renderCrewLeaderboard,
    'page-attacks': renderAttacks,
    'page-bounties': renderBounties,
    'page-informer': renderInformer,
    'page-messages': renderMessages,
    'page-leaderboard': renderLeaderboard,
    'page-respect': renderRespectLeaderboard,
    'page-online': renderOnlinePlayers,
    'page-achievements': renderAchievements,
    'page-settings': renderSettings,
  };

  window.navigateTo = navigateTo;
  function navigateTo(pageId){
    // show the page FIRST so its container has real dimensions before any renderer
    // (e.g. the Leaflet map) measures itself — sizing against a display:none box breaks it
    showPage(pageId);
    const fn = PAGE_RENDERERS[pageId];
    if(fn) fn();

    // Fire-and-forget - lets the Online Players page show what everyone's
    // currently looking at. Plain fetch (not apiCall) so a failed ping never
    // pops an error toast, and never awaited so it can't block navigation.
    if(currentUser){
      fetch('/api/activity/ping', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({page: pageId}),
      }).catch(() => {});
    }

    // Leaderboard pages show everyone else's progress, which can change
    // between polls - paint instantly with whatever's cached, then refresh
    // right away instead of waiting up to 5s for the next background tick.
    if(pageId === 'page-leaderboard' || pageId === 'page-crew-leaderboard'){
      syncState();
    }

    // The Informer and Travel Agent pages get their own background,
    // overriding the current city - restore the real city image the
    // moment you leave.
    const bgScene = document.querySelector('.bg-scene');
    if(bgScene){
      if(pageId === 'page-informer' || pageId === 'page-travel'){
        const img = pageId === 'page-informer' ? './informer.jpg' : './travel%20background.jpg';
        bgScene.style.animation = 'none';
        setTimeout(() => {
          bgScene.style.backgroundImage = `url('${img}')`;
          bgScene.style.animation = 'bgFade 1s ease-in-out';
        }, 10);
        lastBgCity = pageId;
      } else if(lastBgCity === 'page-informer' || lastBgCity === 'page-travel'){
        lastBgCity = null;
        updateBackgroundForCity();
      }
    }
  }

  (function initBetaWelcomeBanner(){
    const banner = document.getElementById('betaWelcomeBanner');
    const closeBtn = document.getElementById('betaWelcomeCloseBtn');
    if(!banner || !closeBtn) return;
    if(localStorage.getItem('betaWelcomeDismissed') === '1'){
      banner.style.display = 'none';
      return;
    }
    closeBtn.addEventListener('click', () => {
      banner.style.display = 'none';
      localStorage.setItem('betaWelcomeDismissed', '1');
    });
  })();

  // The top-strip is now position:fixed so it never scrolls out of view -
  // push the rest of the app down by its real (responsive) height so
  // nothing sits hidden underneath it.
  (function initTopStripOffset(){
    const bar = document.querySelector('.top-strip');
    const shell = document.getElementById('gameContainer');
    if(!bar || !shell) return;
    const apply = () => { shell.style.paddingTop = (bar.offsetHeight + 14) + 'px'; };
    window.updateTopStripOffset = apply;
    apply();
    if(typeof ResizeObserver !== 'undefined'){
      new ResizeObserver(apply).observe(bar);
    } else {
      window.addEventListener('resize', apply);
    }
  })();

  document.querySelectorAll('.sidebar-link').forEach(btn => {
    btn.addEventListener('click', () => navigateTo(btn.dataset.page));
  });
  const homeLink = document.querySelector('.sidebar-link[data-page="page-main"]');
  if(homeLink) homeLink.classList.add('active');
  document.getElementById('topbarLogoBtn').addEventListener('click', () => navigateTo('page-main'));

  document.getElementById('openTravelBtn').addEventListener('click', () => navigateTo('page-travel'));
  document.getElementById('openHeistBtn').addEventListener('click', () => navigateTo('page-heist'));
  document.getElementById('openRealEstateBtn').addEventListener('click', () => navigateTo('page-realestate'));
  document.getElementById('openBlackMarketBtn').addEventListener('click', () => navigateTo('page-blackmarket'));
  document.getElementById('buyMobDollarsBtn').addEventListener('click', buyMobDollars);
  // authToggleBtn's click handler is fully managed by updateAuthUI() below
  // (opens the sign-up modal when logged out, signs out when logged in) -
  // do not also bind it here or both handlers fire on every click.
  if(document.getElementById('authToggleModalBtn')){
    document.getElementById('authToggleModalBtn').addEventListener('click', function(e){
      e.preventDefault();
      const isSignUp = document.getElementById('authPimpIdDiv').style.display !== 'none';
      showAuthModal(!isSignUp);
    });
  }
  if(document.getElementById('authCloseBtn')){
    document.getElementById('authCloseBtn').addEventListener('click', () => {
      document.getElementById('authModal').style.display = 'none';
    });
  }
  if(document.getElementById('authModal')){
    document.getElementById('authModal').addEventListener('click', (e) => {
      if(e.target.id === 'authModal'){
        document.getElementById('authModal').style.display = 'none';
      }
    });
  }
  async function buyMobDollars(){
    try{
      await apiCall('/api/mobdollars/buy');
      showToast('✅ 50 🪙 Mob Dollars purchased!');
      render();
      const slider = document.getElementById('mobDollarsSlider');
      if(slider) slider.max = state.mobDollars || 0;
      updateMobDollarsModal();
      updateBuyMobDollarsCountdown();
    } catch(e){ /* toast already shown */ }
  }

  function updateBuyMobDollarsCountdown(){
    const btn = document.getElementById('buyMobDollarsBtn');
    const countdown = document.getElementById('buyMobDollarsCountdown');
    if(!btn || !countdown) return;

    const now = Date.now();
    const lastPurchase = state.lastRealMoneyPurchase || 0;
    const cooldownMs = 12 * 60 * 60 * 1000; // 12 hours
    const nextAvailable = lastPurchase + cooldownMs;

    if(now >= nextAvailable){
      btn.disabled = false;
      btn.style.opacity = '1';
      countdown.textContent = 'READY!';
      countdown.style.color = 'var(--teal)';
    } else {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      const remaining = nextAvailable - now;
      const hours = Math.floor(remaining / (60 * 60 * 1000));
      const mins = Math.floor((remaining % (60 * 60 * 1000)) / (60 * 1000));
      const secs = Math.floor((remaining % (60 * 1000)) / 1000);
      countdown.textContent = `${hours}h ${mins}m ${secs}s`;
      countdown.style.color = 'var(--text-dim)';
    }
  }


  document.getElementById('buyMedicalBtn').addEventListener('click', () => buyFactory('medical'));
  document.getElementById('buyGunBtn').addEventListener('click', () => buyFactory('gun'));
  document.getElementById('buyCarBtn').addEventListener('click', () => buyFactory('car'));
  document.getElementById('buyDrugBtn').addEventListener('click', () => buyFactory('drug'));
  document.getElementById('carRatioSlider').addEventListener('input', (e) => updateCarMixLabel(parseInt(e.target.value)));
  document.getElementById('carRatioSlider').addEventListener('change', (e) => setCarFactoryRatio(parseInt(e.target.value)));
  document.getElementById('sellAllCadillacsBtn').addEventListener('click', sellAllCadillacs);
  document.getElementById('sellAllMedsBtn').addEventListener('click', sellAllMeds);
  document.getElementById('sellAllCokeDealerBtn').addEventListener('click', sellAllCokeDealer);
  document.getElementById('sellOverseasCokeBtn').addEventListener('click', sellCokeOverseas);
  document.getElementById('collectCounterfeitBtn').addEventListener('click', collectCounterfeit);
  document.getElementById('washCounterfeitBtn').addEventListener('click', washCounterfeit);
  document.querySelectorAll('.lb-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => setLbTab(btn.dataset.lbtab));
  });
  document.getElementById('sellAllTrucksBtn').addEventListener('click', sellAllArmoredTrucks);
  document.getElementById('washFakeMoneyBtn').addEventListener('click', washFakeMoney);
  document.getElementById('washFakeMoneyOverseasBtn').addEventListener('click', washFakeMoneyOverseas);
  document.getElementById('gunRatioSlider').addEventListener('input', (e) => updateGunMixLabel(parseInt(e.target.value)));
  document.getElementById('gunRatioSlider').addEventListener('change', (e) => setGunFactoryRatio(parseInt(e.target.value)));
  document.getElementById('sellAllPistolsBtn').addEventListener('click', () => sellAllGuns('pistol9mm'));
  document.getElementById('sellAllShotgunsBtn').addEventListener('click', () => sellAllGuns('shotgun12gauge'));
  document.getElementById('sellAllAksBtn').addEventListener('click', () => sellAllGuns('ak47'));
  document.getElementById('sellAllM249sBtn').addEventListener('click', () => sellAllGuns('m249'));
  document.getElementById('buyExplosiveBtn').addEventListener('click', () => buyFactory('explosive'));
  document.getElementById('buyCounterfeitBtn').addEventListener('click', () => buyFactory('counterfeit'));
  document.getElementById('buyGymBtn').addEventListener('click', () => buyFactory('gym'));
  document.getElementById('buyWarehouseBtn').addEventListener('click', () => buyFactory('warehouse'));
  ['medical', 'gun', 'car', 'drug', 'explosive', 'counterfeit', 'gym', 'warehouse'].forEach(type => {
    const suffix = FACTORY_ID_SUFFIX[type];
    document.getElementById(`sell${suffix}Slider`).addEventListener('input', () => updateSellFactoryLabel(type));
    document.getElementById(`sell${suffix}Btn`).addEventListener('click', () => {
      const qty = parseInt(document.getElementById(`sell${suffix}Slider`).value) || 0;
      if(qty > 0) sellFactory(type, qty);
    });
    document.getElementById(`buy${suffix}Qty`).addEventListener('input', () => updateBuyFactoryLabel(type));
    document.getElementById(`buy${suffix}MaxBtn`).addEventListener('click', () => setBuyQtyMax(type));
  });
  document.querySelectorAll('[data-back]').forEach(btn => {
    btn.addEventListener('click', () => showPage('page-main'));
  });
  document.getElementById('heistResultBackBtn').addEventListener('click', () => showPage('page-main'));
  document.getElementById('closeDMBtn').addEventListener('click', () => {
    document.getElementById('dmModal').classList.add('hidden');
  });
  document.getElementById('dmModal').addEventListener('click', (e) => {
    if(e.target.id === 'dmModal') document.getElementById('dmModal').classList.add('hidden');
  });
  document.getElementById('closeWorkResultsBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('workResultsModal').classList.add('hidden');
  });
  document.getElementById('workResultsModal').addEventListener('click', (e) => {
    if(e.target.id === 'workResultsModal'){
      e.target.classList.add('hidden');
    }
  });
  document.getElementById('closeAttackResultBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('attackResultModal').classList.add('hidden');
  });
  document.getElementById('attackResultModal').addEventListener('click', (e) => {
    if(e.target.id === 'attackResultModal'){
      e.target.classList.add('hidden');
    }
  });
  document.getElementById('closeBombResultBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('bombResultModal').classList.add('hidden');
  });
  document.getElementById('bombResultModal').addEventListener('click', (e) => {
    if(e.target.id === 'bombResultModal'){
      e.target.classList.add('hidden');
    }
  });
  document.getElementById('doShopBtn').addEventListener('click', () => runHeist('shop'));
  document.getElementById('doJewBtn').addEventListener('click', () => runHeist('jewellery'));
  document.getElementById('doBankBtn').addEventListener('click', () => runHeist('bank'));
  document.getElementById('doCasinoBtn').addEventListener('click', runCasinoHeist);

  // ---- Wire up ----
  document.getElementById('turnSlider').addEventListener('blur', (e)=>{
    const max = parseInt(e.target.max) || 150;
    let v = parseInt(e.target.value) || 1;
    v = Math.max(1, Math.min(v, max));
    e.target.value = v;
  });
  document.querySelectorAll('.quickbtns button').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const v = btn.dataset.v === 'MAX' || parseInt(btn.dataset.v) > state.turns
        ? Math.min(150, state.turns)
        : parseInt(btn.dataset.v);
      const input = document.getElementById('turnSlider');
      input.value = Math.min(v, parseInt(input.max));
    });
  });
  document.getElementById('workBtn').addEventListener('click', workBlock);
  document.getElementById('locRedLight').addEventListener('click', () => setWorkLocation('redlight'));
  document.getElementById('locNightclub').addEventListener('click', () => setWorkLocation('nightclub'));
  document.getElementById('locPullup').addEventListener('click', () => setWorkLocation('pullup'));
  document.getElementById('mobDollarsBtn').addEventListener('click', openMobDollarsModal);
  document.getElementById('mobDollarsCloseBtn').addEventListener('click', () => {
    document.getElementById('mobDollarsModal').classList.add('hidden');
  });
  document.getElementById('mobDollarsModal').addEventListener('click', (e) => {
    if(e.target.id === 'mobDollarsModal') document.getElementById('mobDollarsModal').classList.add('hidden');
  });
  document.getElementById('mobDollarsSlider').addEventListener('input', updateMobDollarsModal);
  document.getElementById('mobDollarsSpendBtn').addEventListener('click', spendMobDollars);
  document.getElementById('bribeBtn').addEventListener('click', bribeCops);
  document.getElementById('layLowBtn').addEventListener('click', layLow);
  document.getElementById('crewChatSendBtn').addEventListener('click', sendCrewChatMessage);
  document.getElementById('crewChatInput').addEventListener('keydown', (e) => {
    if(e.key === 'Enter') sendCrewChatMessage();
  });
  document.getElementById('globalChatSendBtn').addEventListener('click', sendGlobalChatMessage);
  document.getElementById('globalChatInput').addEventListener('keydown', (e) => {
    if(e.key === 'Enter') sendGlobalChatMessage();
  });
  document.getElementById('resetBtn').addEventListener('click', resetGame);
  document.getElementById('referFriendBtn').addEventListener('click', () => {
    if(!currentUser){
      showToast('Sign up or log in first to get your invite link!');
      return;
    }
    const link = `${window.location.origin}/?ref=${currentUser.id}`;
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(link).then(() => showToast('🪙 Invite link copied! Share it to earn Mob Dollars.'));
    }
    navigateTo('page-settings');
  });
  document.getElementById('copyReferralLinkBtn').addEventListener('click', () => {
    const input = document.getElementById('referralLinkInput');
    input.select();
    input.setSelectionRange(0, 99999);
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(input.value).then(() => showToast('🪙 Referral link copied!'));
    } else {
      document.execCommand('copy');
      showToast('🪙 Referral link copied!');
    }
  });
  document.getElementById('savePimpNameBtn').addEventListener('click', savePimpName);
  document.getElementById('saveBioBtn').addEventListener('click', saveBio);
  document.getElementById('bioInput').addEventListener('input', updateBioCharCount);
  document.getElementById('viewOwnProfileBtn').addEventListener('click', openOwnProfile);
  document.getElementById('saveCrewNameBtn').addEventListener('click', saveCrewName);
  document.getElementById('workResultsToggle').addEventListener('change', (e) => {
    state.showWorkResults = e.target.checked;
    save();
  });
  document.getElementById('tutorialToggle').addEventListener('change', async (e) => {
    try{
      await apiCall('/api/settings/tutorial', {enabled: e.target.checked});
    } catch(err){ /* toast already shown */ }
  });
  document.getElementById('pushToggleBtn').addEventListener('click', async () => {
    const sub = await getPushSubscription();
    if(sub) disablePushNotifications(); else enablePushNotifications();
  });
  document.getElementById('tutorialNextBtn').addEventListener('click', () => {
    if(tutorialStep >= TUTORIAL_STEPS.length - 1){
      closeTutorial();
    } else {
      tutorialStep++;
      renderTutorialStep();
    }
  });
  document.getElementById('tutorialBackBtn').addEventListener('click', () => {
    if(tutorialStep > 0){
      tutorialStep--;
      renderTutorialStep();
    }
  });
  document.getElementById('tutorialSkipBtn').addEventListener('click', closeTutorial);
  document.getElementById('crewPowerBtn').addEventListener('click', () => navigateTo('page-crew-leaderboard'));
  document.getElementById('playerMsgBtn').addEventListener('click', () => navigateTo('page-messages'));
  document.getElementById('informerTargetSelect').addEventListener('change', updateInformerCostPreview);
  document.getElementById('informerBuyBtn').addEventListener('click', buyInformerReport);
  document.getElementById('postBountyBtn').addEventListener('click', postBounty);
  document.getElementById('quickBuyMedsBtn').addEventListener('click', quickBuyMeds);
  document.getElementById('hoMedsSlider').addEventListener('input', updateMedsOverlayQty);

  async function syncState(){
    if(!currentUser) return;
    try{
      const res = await fetch('/api/state');
      const data = await res.json();
      if(data.success && data.state){
        state = data.state;
        render();
        const lbPage = document.getElementById('page-leaderboard');
        if(lbPage && lbPage.classList.contains('active')){
          renderLeaderboard();
        }
        const heistPage = document.getElementById('page-heist');
        if(heistPage && heistPage.classList.contains('active')){
          renderTheMint();
        }
      }
    } catch(e){ /* silent - next tick retries */ }
  }

  async function syncLeaderboardIfActive(){
    const lbPage = document.getElementById('page-leaderboard');
    if(lbPage && lbPage.classList.contains('active')){
      await syncState();
    }
  }

  // ---- Background music ----
  // Browsers block audio autoplay until the user interacts with the page,
  // so we start it on the first click/keypress rather than on load.
  (function initMusic(){
    const audio = document.getElementById('bgMusic');
    const btn = document.getElementById('musicToggleBtn');
    if(!audio || !btn) return;

    audio.volume = 0.25;
    let muted = localStorage.getItem('pimpempires-music-muted') === 'true';
    let started = false;

    function updateIcon(){ btn.textContent = muted ? '🔇' : '🔊'; }
    updateIcon();

    function tryStart(){
      if(started || muted) return;
      audio.play().then(() => { started = true; }).catch(() => {});
    }

    // First user gesture anywhere on the page unlocks autoplay
    ['click', 'keydown'].forEach(evt => {
      document.addEventListener(evt, tryStart, {once: true});
    });

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      muted = !muted;
      localStorage.setItem('pimpempires-music-muted', muted);
      updateIcon();
      if(muted){
        audio.pause();
      } else {
        started = true;
        audio.play().catch(() => {});
      }
    });
  })();

  initAuth().then(load).then(()=>{
    setInterval(tickRegen, 1000);
    setInterval(updateTimers, 1000);
    setInterval(syncState, 20000);
    setInterval(syncLeaderboardIfActive, 5000);

    maybeShowTutorial();

    // Escape key closes modals
    document.addEventListener('keydown', (e) => {
      if(e.key === 'Escape'){
        document.getElementById('workResultsModal').classList.add('hidden');
        document.getElementById('attackResultModal').classList.add('hidden');
        document.getElementById('dmModal').classList.add('hidden');
        closeTutorial();
        if(document.getElementById('authModal')){
          document.getElementById('authModal').style.display = 'none';
        }
      }
    });
  });
})();


    document.querySelectorAll('.bnav-btn[data-page]').forEach(btn => {
      btn.addEventListener('click', () => {
        navigateTo(btn.dataset.page);
        closeMoreDrawer();
      });
    });
    document.querySelectorAll('.drawer-link').forEach(btn => {
      btn.addEventListener('click', () => {
        navigateTo(btn.dataset.page);
        closeMoreDrawer();
      });
    });

    const moreDrawer = document.getElementById('moreDrawer');
    const moreDrawerOverlay = document.getElementById('moreDrawerOverlay');
    
    document.getElementById('openMoreDrawerBtn').addEventListener('click', () => {
      moreDrawer.classList.add('active');
      moreDrawerOverlay.classList.add('active');
    });
    
    function closeMoreDrawer() {
      moreDrawer.classList.remove('active');
      moreDrawerOverlay.classList.remove('active');
    }
    
    document.getElementById('closeMoreDrawerBtn').addEventListener('click', closeMoreDrawer);
    moreDrawerOverlay.addEventListener('click', closeMoreDrawer);
  
