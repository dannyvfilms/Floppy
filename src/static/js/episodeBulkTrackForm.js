// Bind once: this script is re-evaluated on boosted (hx-boost) navigation.
if (!window.__floppyEpisodeBulkTrackFormBound) {
  window.__floppyEpisodeBulkTrackFormBound = true;
  document.addEventListener("alpine:init", () => {
  Alpine.data("episodeBulkTrackForm", (domainId) => ({
    domain: null,
    firstSeason: "",
    firstEpisode: "",
    lastSeason: "",
    lastEpisode: "",
    writeMode: "add",
    distributionMode: "air_date",
    summaryText: gettext("Choose the first and last item to log a bulk play range."),
    rangeWarning: "",

    init() {
      const script = document.getElementById(domainId);
      if (!script) {
        return;
      }

      this.domain = JSON.parse(script.textContent);
      this.firstSeason =
        this.$refs.firstSeason.value ||
        String(this.domain.defaultFirst.season_number);
      this.lastSeason =
        this.$refs.lastSeason.value ||
        String(this.domain.defaultLast.season_number);
      this.firstEpisode =
        this.$refs.firstEpisode.dataset.currentValue ||
        String(this.domain.defaultFirst.episode_number);
      this.lastEpisode =
        this.$refs.lastEpisode.dataset.currentValue ||
        String(this.domain.defaultLast.episode_number);

      this.syncEpisodeOptions("first");
      this.syncEpisodeOptions("last");
      this.writeMode =
        this.$el.querySelector('[name="write_mode"]')?.value || "add";
      this.distributionMode =
        this.$el.querySelector('[name="distribution_mode"]')?.value ||
        "air_date";
      this.refreshSummary();
    },

    selectionNoun() {
      return gettext(this.domain?.selectionNoun || "episode");
    },

    selectionNounPlural() {
      return gettext(this.domain?.selectionNounPlural || "episodes");
    },

    distributionTargetLabel() {
      return gettext(this.domain?.distributionTargetLabel || "air date");
    },

    missingTargetDateFallbackDistribution() {
      return this.domain?.missingTargetDateFallbackDistribution || "";
    },

    seasonEpisodes(seasonNumber) {
      if (!this.domain) {
        return [];
      }
      return this.domain.seasonEpisodeMap[String(seasonNumber)] || [];
    },

    pad(value) {
      return String(value).padStart(2, "0");
    },

    selectedEpisode(side) {
      const seasonNumber = side === "first" ? this.firstSeason : this.lastSeason;
      const episodeNumber = side === "first" ? this.firstEpisode : this.lastEpisode;

      return this.seasonEpisodes(seasonNumber).find(
        (episode) => String(episode.episode_number) === String(episodeNumber),
      );
    },

    selectedEpisodeAirDate(side) {
      return this.selectedEpisode(side)?.air_date || "";
    },

    selectedEpisodeRuntime(side) {
      return this.selectedEpisode(side)?.runtime_minutes || "";
    },

    syncEpisodeOptions(side) {
      const isFirst = side === "first";
      const select = isFirst ? this.$refs.firstEpisode : this.$refs.lastEpisode;
      const seasonNumber = isFirst ? this.firstSeason : this.lastSeason;
      const currentValue = isFirst ? this.firstEpisode : this.lastEpisode;
      const episodes = this.seasonEpisodes(seasonNumber);

      while (select.firstChild) {
        select.removeChild(select.firstChild);
      }

      episodes.forEach((episode) => {
        const option = document.createElement("option");
        option.value = String(episode.episode_number);
        option.textContent =
          episode.selector_label ||
          `E${episode.episode_number} - ${episode.episode_title}`;
        select.appendChild(option);
      });

      const hasCurrentValue = episodes.some(
        (episode) => String(episode.episode_number) === String(currentValue),
      );
      if (hasCurrentValue) {
        select.value = String(currentValue);
      } else if (episodes.length > 0) {
        select.value = String(
          isFirst
            ? episodes[0].episode_number
            : episodes[episodes.length - 1].episode_number,
        );
      }

      if (isFirst) {
        this.firstEpisode = select.value;
      } else {
        this.lastEpisode = select.value;
      }
      this.refreshSummary();
    },

    selectedRangeEpisodes() {
      if (!this.domain) {
        return [];
      }

      const firstEpisode = this.selectedEpisode("first");
      const lastEpisode = this.selectedEpisode("last");

      if (!firstEpisode || !lastEpisode) {
        return [];
      }

      const allEpisodes = Object.values(this.domain.seasonEpisodeMap).flat();
      return allEpisodes.filter(
        (episode) =>
          firstEpisode.order <= episode.order &&
          episode.order <= lastEpisode.order,
      );
    },

    refreshSummary() {
      const selectedEpisodes = this.selectedRangeEpisodes();
      if (selectedEpisodes.length === 0) {
        this.summaryText =
          gettext("Choose a valid ordered range to log plays.");
        this.rangeWarning = "";
        return;
      }

      const existingPlayCount = selectedEpisodes.reduce(
        (total, episode) => total + (episode.existing_play_count || 0),
        0,
      );
      const distributionLabel = this.distributionMode === "air_date"
        ? gettext("the target dates within the selected date range")
        : gettext("an even distribution across the date range");
      const summary = this.writeMode === "replace"
        ? ngettext("This will replace plays for %(count)s ordered item using %(distribution)s.", "This will replace plays for %(count)s ordered items using %(distribution)s.", selectedEpisodes.length)
        : ngettext("This will add plays for %(count)s ordered item using %(distribution)s.", "This will add plays for %(count)s ordered items using %(distribution)s.", selectedEpisodes.length);
      this.summaryText = interpolate(summary, {
        count: selectedEpisodes.length, distribution: distributionLabel,
      }, true);

      if (this.distributionMode === "air_date") {
        const missingAirDates = selectedEpisodes.filter(
          (episode) => !episode.air_date,
        ).length;
        if (missingAirDates > 0) {
          const fallbackDistribution =
            this.missingTargetDateFallbackDistribution();
          this.rangeWarning = interpolate(
            ngettext("%(count)s selected item has no target date.", "%(count)s selected items have no target date.", missingAirDates),
            { count: missingAirDates }, true,
          ) + (fallbackDistribution === "even"
            ? " " + gettext("Saving will fall back to even distribution.")
            : "");
          return;
        }
      }

      if (this.writeMode === "replace") {
        this.rangeWarning =
          existingPlayCount > 0
            ? interpolate(ngettext("This will delete %(count)s existing play in the selected range before adding the new ordered pass.", "This will delete %(count)s existing plays in the selected range before adding the new ordered pass.", existingPlayCount), { count: existingPlayCount }, true)
            : gettext("No existing plays are currently logged in the selected range.");
        return;
      }

      this.rangeWarning =
        existingPlayCount > 0
          ? interpolate(ngettext("This range already has %(count)s logged play. New plays will be appended in order.", "This range already has %(count)s logged plays. New plays will be appended in order.", existingPlayCount), { count: existingPlayCount }, true)
          : "";
    },
  }));
  });
}
