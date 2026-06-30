package org.swam.pn_utils;

import org.oristool.petrinet.*;

public final class PetriNetUtils {
    private PetriNetUtils() {
        // Private constructor to prevent instantiation
    }

    public static Place findPlaceByName(PetriNet pn, String name) {
        return pn.getPlaces().stream()
            .filter(place -> place.getName().equals(name))
            .findFirst()
            .orElseThrow(() -> new IllegalArgumentException("Place not found: " + name));
    }

    public static Transition findTransitionByName(PetriNet pn, String name) {
        return pn.getTransitions().stream()
                .filter(trans -> trans.getName().equals(name))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Transition not found: " + name));
    }

    public static Transition findOrCreateTransitionByName(PetriNet pn, String name) {
        return pn.getTransitions().stream()
                .filter(trans -> trans.getName().equals(name))
                .findFirst()
                .orElseGet(() -> pn.addTransition(name));
    }

    public static void checkNetAndMarking(PetriNet pn, Marking marking) {
        if (pn == null || marking == null) {
            throw new IllegalStateException("Petri net and marking must be created first.");
        }
    }
}
