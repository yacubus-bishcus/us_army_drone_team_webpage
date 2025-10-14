(function () {
    "use strict";
  
    function setStatus(target, message, type) {
      if (!target) {
        return;
      }
      target.textContent = message || "";
      target.dataset.statusType = type || "";
    }
  
    document.addEventListener("DOMContentLoaded", function () {
      var form = document.getElementById("velocidrone-request-form");
      if (!form) {
        return;
      }
  
      var status = document.getElementById("velocidrone-status");
      var submit = form.querySelector("button[type='submit']");
      var sessionUrl = form.getAttribute("data-session-url");
  
      form.addEventListener("submit", function (event) {
        event.preventDefault();

        if (!sessionUrl) {
          setStatus(status, "Velocidrone integration is not configured.", "error");
          return;
        }

        var callsignAttr = form.getAttribute("data-callsign") || "";
        var callsign = callsignAttr.trim();
        if (!callsign) {
          setStatus(status, "Velocidrone callsign not found. Submit an application first.", "error");
          return;
        }

        setStatus(status, "Requesting secure login…", "pending");
        if (submit) {
          submit.disabled = true;
        }
  
        fetch(sessionUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest"
          },
          body: JSON.stringify({ callsign: callsign })
        })
          .then(function (response) {
            if (!response.ok) {
              return response.json().catch(function () {
                return { error: "Unable to request Velocidrone access." };
              }).then(function (data) {
                throw new Error(data.error || "Unable to request Velocidrone access.");
              });
            }
            return response.json();
          })
          .then(function (data) {
            if (!data || !data.launchUrl) {
              throw new Error("Invalid response from Velocidrone integration.");
            }
            setStatus(status, "Opening secure Velocidrone session…", "success");
            window.location.href = data.launchUrl;
          })
          .catch(function (error) {
            setStatus(status, error.message, "error");
          })
          .finally(function () {
            if (submit) {
              submit.disabled = false;
            }
          });
      });
    });
  })();