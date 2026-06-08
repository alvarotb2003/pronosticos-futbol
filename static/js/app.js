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

    homeSelect.innerHTML = "<option value=''>Selecciona equipo local</option>";
    awaySelect.innerHTML = "<option value=''>Selecciona equipo visitante</option>";

    data.teams.forEach(team => {
        const opt1 = document.createElement("option");
        opt1.value = team.id;
        opt1.textContent = team.name;

        const opt2 = document.createElement("option");
        opt2.value = team.id;
        opt2.textContent = team.name;

        homeSelect.appendChild(opt1);
        awaySelect.appendChild(opt2);
    });
}


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

    const res = await fetch(url);
    const data = await res.json();

    if (data.error) {
        resultContent.innerHTML = `
            <p class="error">${data.error}</p>
            <pre>${JSON.stringify(data, null, 2)}</pre>
        `;
        return;
    }

    renderPrediction(data);
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


function renderPrediction(data) {
    const resultContent = document.getElementById("resultContent");

    let scoresHtml = "";

    data.top_scores.forEach(item => {
        scoresHtml += `<li>${item.score} - ${item.probability}%</li>`;
    });

    resultContent.innerHTML = `
        <div class="result">
            <h3>${data.match}</h3>

            <div class="summary-box">
                <h4>Recomendación principal</h4>
                <p>
                    <span class="good">${data.recommendation.market}</span>
                    con ${data.recommendation.probability}%
                </p>
                <p>
                    Confianza:
                    <span class="warn">${data.recommendation.confidence}</span>
                </p>
            </div>

            <h4>Goles esperados</h4>
            <p>Equipo 1 / Local: ${data.expected_goals.home}</p>
            <p>Equipo 2 / Visitante: ${data.expected_goals.away}</p>

            <h4>Probabilidades 1X2</h4>
            ${probabilityBar("Gana Equipo 1 / Local", data.probabilities.home_win)}
            ${probabilityBar("Empate", data.probabilities.draw)}
            ${probabilityBar("Gana Equipo 2 / Visitante", data.probabilities.away_win)}

            <h4>Mercado de goles</h4>
            ${probabilityBar("Más de 2.5 goles", data.probabilities.over_25)}
            ${probabilityBar("Menos de 2.5 goles", data.probabilities.under_25)}

            <h4>Ambos equipos anotan</h4>
            ${probabilityBar("Sí", data.probabilities.btts_yes)}
            ${probabilityBar("No", data.probabilities.btts_no)}

            <h4>Marcadores más probables</h4>
            <ol>${scoresHtml}</ol>
        </div>
    `;
}