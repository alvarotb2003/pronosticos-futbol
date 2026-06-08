let teamsList = [];

function updateSeasonOptions() {
    const league = document.getElementById("league").value;
    const seasonSelect = document.getElementById("season");
    
    seasonSelect.innerHTML = "";
    
    let seasons = [];
    if (league === "WC") {
        seasons = [2026];
    } else if (league === "EC") {
        seasons = [2024];
    } else {
        // Ligas estándar nacionales y Champions League
        seasons = [2025, 2024, 2023];
    }
    
    seasons.forEach(year => {
        const opt = document.createElement("option");
        opt.value = year;
        opt.textContent = year;
        seasonSelect.appendChild(opt);
    });
}

function updateTeamCrests() {
    const homeSelect = document.getElementById("homeTeam");
    const awaySelect = document.getElementById("awayTeam");

    const homeCrestBox = document.getElementById("homeCrestBox");
    const awayCrestBox = document.getElementById("awayCrestBox");

    const selectedHomeOpt = homeSelect.options[homeSelect.selectedIndex];
    const selectedAwayOpt = awaySelect.options[awaySelect.selectedIndex];

    if (selectedHomeOpt && selectedHomeOpt.dataset.crest) {
        homeCrestBox.innerHTML = `<img src="${selectedHomeOpt.dataset.crest}" alt="logo">`;
    } else {
        homeCrestBox.innerHTML = "⚽";
    }

    if (selectedAwayOpt && selectedAwayOpt.dataset.crest) {
        awayCrestBox.innerHTML = `<img src="${selectedAwayOpt.dataset.crest}" alt="logo">`;
    } else {
        awayCrestBox.innerHTML = "⚽";
    }
}

function populateSelectors() {
    const homeSelect = document.getElementById("homeTeam");
    const awaySelect = document.getElementById("awayTeam");

    const prevHome = homeSelect.value;
    const prevAway = awaySelect.value;

    homeSelect.innerHTML = "<option value=''>Selecciona equipo local</option>";
    awaySelect.innerHTML = "<option value=''>Selecciona equipo visitante</option>";

    teamsList.forEach(team => {
        // Excluir el equipo seleccionado en el otro selector
        if (team.id != prevAway || !prevAway) {
            const opt = document.createElement("option");
            opt.value = team.id;
            opt.textContent = team.name;
            opt.dataset.crest = team.crest || "";
            homeSelect.appendChild(opt);
        }
        if (team.id != prevHome || !prevHome) {
            const opt = document.createElement("option");
            opt.value = team.id;
            opt.textContent = team.name;
            opt.dataset.crest = team.crest || "";
            awaySelect.appendChild(opt);
        }
    });

    homeSelect.value = prevHome;
    awaySelect.value = prevAway;

    updateTeamCrests();
}

async function loadTeams() {
    const league = document.getElementById("league").value;
    const season = document.getElementById("season").value;

    const homeSelect = document.getElementById("homeTeam");
    const awaySelect = document.getElementById("awayTeam");

    homeSelect.innerHTML = "<option>Cargando equipos...</option>";
    awaySelect.innerHTML = "<option>Cargando equipos...</option>";

    const res = await fetch(`/api/teams-by-league?league=${league}&season=${season}`);
    const data = await res.json();

    if (data.message || !data.teams) {
        homeSelect.innerHTML = "<option>Error al cargar</option>";
        awaySelect.innerHTML = "<option>Error al cargar</option>";
        alert(data.message || "Error al obtener equipos del torneo. Es posible que la temporada seleccionada no esté soportada o requiera plan de pago.");
        return;
    }

    if (data.teams.length === 0) {
        homeSelect.innerHTML = "<option>No hay equipos</option>";
        awaySelect.innerHTML = "<option>No hay equipos</option>";
        alert("No se encontraron equipos para ese torneo/temporada.");
        return;
    }

    teamsList = data.teams;
    populateSelectors();
}

// Escuchar cambios para aplicar la deduplicación de opciones en tiempo real
document.getElementById("homeTeam").addEventListener("change", populateSelectors);
document.getElementById("awayTeam").addEventListener("change", populateSelectors);


async function calculatePrediction() {
    const league = document.getElementById("league").value;
    const season = document.getElementById("season").value;

    const homeSelect = document.getElementById("homeTeam");
    const awaySelect = document.getElementById("awayTeam");

    const home = homeSelect.value;
    const away = awaySelect.value;

    if (!home || !away) {
        alert("Selecciona ambos equipos.");
        return;
    }

    if (home === away) {
        alert("No puedes seleccionar el mismo equipo dos veces.");
        return;
    }

    const homeName = homeSelect.options[homeSelect.selectedIndex].textContent;
    const awayName = awaySelect.options[awaySelect.selectedIndex].textContent;

    const resultCard = document.getElementById("resultCard");
    const resultContent = document.getElementById("resultContent");

    resultCard.style.display = "block";
    resultContent.innerHTML = "Calculando probabilidades...";

    const url = `/api/custom-prediction?league=${league}&season=${season}&home=${home}&away=${away}&home_name=${encodeURIComponent(homeName)}&away_name=${encodeURIComponent(awayName)}`;

    try {
        const res = await fetch(url);
        const data = await res.json();

        if (data.error) {
            resultContent.innerHTML = `
                <p class="error">${data.error}</p>
                <pre>${JSON.stringify(data, null, 2)}</pre>
            `;
            return;
        }

        if (data.insufficient_data) {
            resultContent.innerHTML = `
                <div class="result" style="text-align: center; padding: 20px;">
                    <div style="background: #fee2e2; color: #991b1b; padding: 15px; border-radius: 8px; font-weight: bold; border: 1px solid #fca5a5; margin-bottom: 15px;">
                        ⚠️ Datos Insuficientes
                    </div>
                    <p style="color: #4b5563; font-size: 1.05em; line-height: 1.5; margin-bottom: 0;">${data.message}</p>
                </div>
            `;
            return;
        }

        renderPrediction(data);
    } catch (error) {
        resultContent.innerHTML = `
            <div class="result" style="text-align: center; padding: 20px;">
                <div style="background: #fee2e2; color: #991b1b; padding: 15px; border-radius: 8px; font-weight: bold; border: 1px solid #fca5a5; margin-bottom: 15px;">
                    ⚠️ Error al Calcular
                </div>
                <p style="color: #4b5563; font-size: 1.05em; line-height: 1.5; margin-bottom: 0;">Ocurrió un error al obtener la predicción: ${error.message}</p>
            </div>
        `;
    }
}


function probabilityBar(label, value) {
    const safeValue = Math.max(0, Math.min(100, value));

    return `
        <p><strong>${label}:</strong> ${value}%</p>
        <div class="bar-box">
            <div class="bar" style="width:${safeValue}%">${value}%</div>
        </div>
    `;
}


function renderFormBadges(formStr) {
    if (!formStr) return "<span class='small'>Sin racha reciente</span>";
    const chars = formStr.includes(",") ? formStr.split(",") : formStr.split("");
    let html = "<div class='form-container'>";
    chars.forEach(char => {
        const c = char.trim().toUpperCase();
        let cls = "badge-d";
        if (c === "W") cls = "badge-w";
        else if (c === "L") cls = "badge-l";
        html += `<span class="badge ${cls}">${c}</span>`;
    });
    html += "</div>";
    return html;
}


function renderPrediction(data) {
    const resultContent = document.getElementById("resultContent");
    const [homeName, awayName] = data.match.split(" vs ");

    let scoresHtml = "<div class='score-grid'>";
    data.top_scores.forEach(item => {
        scoresHtml += `
            <div class="score-card">
                <div class="val">${item.score}</div>
                <div class="pct">${item.probability}%</div>
            </div>
        `;
    });
    scoresHtml += "</div>";

    const homeCrestHtml = data.home_stats.crest ? `<img class="title-crest" src="${data.home_stats.crest}" alt="" onerror="this.style.display='none'">` : "";
    const awayCrestHtml = data.away_stats.crest ? `<img class="title-crest" src="${data.away_stats.crest}" alt="" onerror="this.style.display='none'">` : "";

    const tableHomeCrestHtml = data.home_stats.crest ? `<img class="table-crest" src="${data.home_stats.crest}" alt="" onerror="this.style.display='none'">` : "";
    const tableAwayCrestHtml = data.away_stats.crest ? `<img class="table-crest" src="${data.away_stats.crest}" alt="" onerror="this.style.display='none'">` : "";
    // Banner de advertencia si la calidad de los datos es Limitada o Estimada por ELO
    let warningHtml = "";
    if (data.data_quality === "Limitada") {
        warningHtml = `
            <div style="background: #fffbeb; color: #b45309; padding: 12px; border-radius: 6px; border: 1px solid #fde68a; margin-bottom: 15px; font-size: 0.9em; line-height: 1.4; text-align: left;">
                <strong>⚠️ Advertencia:</strong> Datos limitados en el torneo actual para uno o ambos equipos. Las predicciones tienen un margen de error más alto.
            </div>
        `;
    } else if (data.data_quality === "Estimada (Basada en ELO)") {
        warningHtml = `
            <div style="background: #fdf2f2; color: #9b1c1c; padding: 12px; border-radius: 6px; border: 1px solid #fde8e8; margin-bottom: 15px; font-size: 0.9em; line-height: 1.4; text-align: left;">
                <strong>⚠️ Datos Estimados mediante ELO:</strong> Estos equipos aún no tienen partidos finalizados en este torneo. Las probabilidades se han calculado utilizando el sistema de fuerza ELO histórico base.
            </div>
        `;
    }

    // Badge de calidad de datos
    let qualityColor = "#16a34a"; // Excelente (verde)
    if (data.data_quality === "Buena") qualityColor = "#0284c7"; // Azul
    if (data.data_quality === "Limitada") qualityColor = "#d97706"; // Ámbar
    if (data.data_quality === "Estimada (Basada en ELO)") qualityColor = "#9b1c1c"; // Rojo oscuro

    const qualityBadgeHtml = `
        <div style="margin: 10px 0 15px 0; text-align: center;">
            <span style="display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; background: #f1f5f9; color: #475569; font-size: 0.85em; border: 1px solid #cbd5e1;">
                Calidad de datos: <span style="color: ${qualityColor};">${data.data_quality}</span>
            </span>
        </div>
    `;

    resultContent.innerHTML = `
        <div class="result">
            <h3>
                ${homeCrestHtml}
                <span>${homeName}</span>
                <span style="margin: 0 10px; color: #64748b;">vs</span>
                <span>${awayName}</span>
                ${awayCrestHtml}
            </h3>

            ${qualityBadgeHtml}
            ${warningHtml}

            <div class="summary-box">
                <h4>Recomendación principal</h4>
                <p>
                    <span class="good">${data.recommendation.market}</span>
                    con ${data.recommendation.probability}%
                </p>
                <p>
                    Confianza:
                    <span class="warn" style="${data.recommendation.confidence === 'Muy Baja' ? 'color: #ef4444; font-weight: bold;' : ''}">
                        ${data.recommendation.confidence} (${data.recommendation.confidence_val}%)
                    </span>
                </p>
            </div>

            <h4>Comparativa H2H (Rendimiento)</h4>
            <table class="stats-table">
                <thead>
                    <tr>
                        <th>Rendimiento</th>
                        <th>${tableHomeCrestHtml}${homeName}</th>
                        <th>${tableAwayCrestHtml}${awayName}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Sistema ELO (Fuerza)</td>
                        <td><strong>${data.home_stats.elo}</strong></td>
                        <td><strong>${data.away_stats.elo}</strong></td>
                    </tr>
                    <tr>
                        <td>Partidos Jugados</td>
                        <td>${data.home_stats.played}</td>
                        <td>${data.away_stats.played}</td>
                    </tr>
                    <tr>
                        <td>V / E / D</td>
                        <td>${data.home_stats.won} / ${data.home_stats.draw} / ${data.home_stats.lost}</td>
                        <td>${data.away_stats.won} / ${data.away_stats.draw} / ${data.away_stats.lost}</td>
                    </tr>
                    <tr>
                        <td>Goles Anotados (Promedio)</td>
                        <td>${data.home_stats.goals_for} (<strong>${data.home_stats.avg_for}</strong>)</td>
                        <td>${data.away_stats.goals_for} (<strong>${data.away_stats.avg_for}</strong>)</td>
                    </tr>
                    <tr>
                        <td>Goles Recibidos (Promedio)</td>
                        <td>${data.home_stats.goals_against} (<strong>${data.home_stats.avg_against}</strong>)</td>
                        <td>${data.away_stats.goals_against} (<strong>${data.away_stats.avg_against}</strong>)</td>
                    </tr>
                    <tr>
                        <td>Racha Reciente</td>
                        <td>${renderFormBadges(data.home_stats.form)}</td>
                        <td>${renderFormBadges(data.away_stats.form)}</td>
                    </tr>
                </tbody>
            </table>

            <h4>Goles esperados del partido (xG)</h4>
            <p><strong>${homeName}</strong>: ${data.expected_goals.home}</p>
            <p><strong>${awayName}</strong>: ${data.expected_goals.away}</p>

            <h4>Probabilidades de Resultado (1X2)</h4>
            ${probabilityBar(`Gana ${homeName}`, data.probabilities.home_win)}
            ${probabilityBar("Empate", data.probabilities.draw)}
            ${probabilityBar(`Gana ${awayName}`, data.probabilities.away_win)}

            <h4>Doble Oportunidad</h4>
            ${probabilityBar(`Gana ${homeName} o Empate (1X)`, data.probabilities.dc_1x)}
            ${probabilityBar(`Gana ${awayName} o Empate (X2)`, data.probabilities.dc_x2)}
            ${probabilityBar(`Gana ${homeName} o Gana ${awayName} (12)`, data.probabilities.dc_12)}

            <h4>Mercado de goles (Over/Under)</h4>
            ${probabilityBar("Más de 2.5 goles", data.probabilities.over_25)}
            ${probabilityBar("Menos de 2.5 goles", data.probabilities.under_25)}

            <h4>Ambos equipos anotan</h4>
            ${probabilityBar("Sí, ambos anotan", data.probabilities.btts_yes)}
            ${probabilityBar("No anotan ambos", data.probabilities.btts_no)}

            <h4>Marcadores más probables (Matriz de 0-0 a 8-8)</h4>
            ${scoresHtml}
        </div>
    `;
}

// Inicializar las temporadas disponibles al cargar la página
document.addEventListener("DOMContentLoaded", () => {
    updateSeasonOptions();
});