package org.util;

import org.oristool.models.pn.PostUpdater;
import org.oristool.petrinet.*;

public class PetriNetBuilder {
    private PetriNet petriNet;
    private Marking initialMarking;

    public PetriNetBuilder() {
        this.petriNet = new PetriNet();
        this.initialMarking = new Marking();
    }

    public PetriNetBuilder(PetriNet petriNet, Marking marking) {
        this.petriNet = petriNet;
        this.initialMarking = marking;
    }

    public PetriNetBuilder addPlace(String placeName) {
        petriNet.addPlace(placeName);
        return this;
    }

    public PetriNetBuilder addPlace(String placeName, int tokens) {
        Place place = petriNet.addPlace(placeName);
        initialMarking.addTokens(place, tokens);
        return this;
    }

    public PetriNetBuilder addTransition(String transitionName, String prePlaceName, String postPlaceName, TransitionFeature feature) {
        Transition transition = petriNet.addTransition(transitionName);
        transition.addFeature(feature);

        if (prePlaceName != null) {
            Place prePlace = petriNet.getPlace(prePlaceName);
            petriNet.addPrecondition(prePlace, transition);
        }

        if (postPlaceName != null) {
            Place postPlace = petriNet.getPlace(postPlaceName);
            petriNet.addPostcondition(transition, postPlace);
        }
        return this;
    }

    public PetriNetBuilder addFeatureToTransition(String transitionName, TransitionFeature feature) {
        petriNet.getTransition(transitionName).addFeature(feature);
        return this;
    }


    public PetriNetBuilder addEnablingFunctionToTransition(String transitionName, String stringEnablingFunction) {
        EnablingFunction function = new EnablingFunction(stringEnablingFunction);
        addFeatureToTransition(transitionName, function);
        return this;
    }

    public PetriNetBuilder addMarkingUpdateToTransition(String transitionName, String stringMarkingUpdate) {
        PostUpdater updater = new PostUpdater(stringMarkingUpdate, petriNet);
        addFeatureToTransition(transitionName, updater);
        return this;
    }

    public PetriNetBuilder addMarking(String placeName) {
        return addMarking(placeName, 1);
    }

    public PetriNetBuilder addMarking(String placeName, int tokens) {
        Place place = petriNet.getPlace(placeName);
        initialMarking.addTokens(place, tokens);
        return this;
    }

    public PetriNet build() {
        return petriNet;
    }

    public Marking getInitialMarking() {
        return initialMarking;
    }

}