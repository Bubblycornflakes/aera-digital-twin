# Engineering model v0.1
For a constant-volume completely mixed tank write D for dissolved oxygen and N for ammonium nitrogen. The outlet concentrations equal the tank concentrations. With hours as time and concentrations in mg/L:

    r = rmax N/(KN+N) D/(KO+D)
    dN/dt = Q/V (Nin-N) - r
    dD/dt = Q/V (Din-D) + alpha kLa_max u (beta Csat-D)
            - H L D/(KH+D) - 4.57 r

L is the dimensionless daily loading multiplier. Nonnegative substrate activities enter the reaction terms. Transfer may become negative above process saturation. The model omits biomass growth, temperature dynamics, denitrification, N₂O and sludge age. One basin takes a quarter of the representative flow. This fraction and the kinetics are illustrative. Its energy output cannot validate a 20% aeration saving scenario.

At minute boundaries the controller measures D with optional seeded Gaussian noise and bias. Error e equals target minus measurement. Command is bias + Kp e + integral + Kd (e-e_prev)/dt, limited to [0,1]; suppress an integral increment driving further into saturation. The plant sees constant command and inlet over each interval. Adaptive RK45 integrates the two balances inside the interval. Sum power times interval hours for electricity; the final sample adds no energy.

Daily flow and concentration multiply their means by L=1+0.17cos(2π(t−8)/24)+0.12cos(4π(t−8)/24). The illustrative 12–18h storm multiplies flow by 1.4 and concentration by 0.75, increasing influent nitrogen mass rate 5%. A daily 09–15h return spreads a quarter of 297 kg N/day over six hours at 800 mg N/L; add its water flow and mix by mass. Biological organic demand follows L as an independent proxy. These event schedules repeat daily.

Annual reference: site kWh = PE × specific flow × 365 × specific electricity. Multiply by end-use shares and saving fractions separately before adding. Scope 2 tonnes = grid kWh × grid factor / 1000. Section 4.8 prices returned nitrogen at a rounded 2.03 kWh/kg N; using this rounded input gives 220.06 MWh/year. This penalty applies only to the annual digestion comparison. Sections 4.9–4.11 treat thermal balance, methane slip and investment separately. Sections 5–6 show the conclusions depend on capital, accounting boundary and leakage. Tank oxygen concentration cannot quantify methane or N₂O emissions.
