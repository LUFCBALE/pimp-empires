This PR introduces a comprehensive overhaul of the game's economy and combat mechanics to fix endgame snowballing, alongside major UI/UX improvements.

### ?? 1. The Economy & Factory ROI
- **The Problem:** The old economy was broken because FACTORY_SELL_PRICES were flat ,000 for all factories, and FACTORY_COSTS scaled exponentially. This meant the Rank 5 Drug Factory was mathematically better than all endgame factories, allowing players to reach quadrillions in net worth and bypass the entire late game.
- **The Fix:** Factory costs and production rates were rebalanced into a smoothed curve where higher-tier factories always have a better Return on Investment (ROI) than the previous tier. Rank 7 Counterfeit factories now cost  and have the best ROI in the game.

### ?? 2. PvP & Thug Combat
- **The "Ant vs Boot" Fix:** The combat formula has been rewritten to use a **Power Ratio** calculation instead of flat casualty percentages. Massive Tycoons can now attack small players without losing 90% of their own thugs, and small players are no longer instantly wiped out (max 25% defender casualties).
- **Bombing Rebalance:** Bomb damage has been standardized (1 Bomb = $10,000 of damage). It now costs 10,000 bombs to destroy a $100M factory, perfectly aligning the cost of aggression with the cost of building an economy.

### ?? 3. Turn Economy, Jobs & Progression
- **The Problem:** Active play contributed less than 1% to Rank progression, and Heists were broken because they awarded a flat percentage of Total Net Worth (yielding $15 Billion in one click for Tycoons).
- **The Fix:** 
  - 
etWorthPct payouts for Heists were divided by 100, adapting them to the new $100 Billion Tycoon economy.
  - Job XP is now dynamically tied to the cash payout (cash_won * SELL_XP_PER_POUND). Endgame heists now grant massive XP, turning Jobs into a highly viable endgame progression system.
  - RANKS requirements were smoothed, capping THE DON (Rank 13) at 2.5M XP.
  - Reduced turn regeneration to 40 turns/20min to prevent explosive early-game snowballing.

### ?? 4. UI/UX Styling
- Overhauled the CSS to give the game a more premium aesthetic. Added subtle hover effects, glassmorphism to modals (ackdrop-filter: blur), and distinct visual flair to buttons.

All changes have been run through a 7-day headless simulation script to mathematically verify that the new economy is balanced, predictable, and prevents quadrillion-dollar integer overflows.
