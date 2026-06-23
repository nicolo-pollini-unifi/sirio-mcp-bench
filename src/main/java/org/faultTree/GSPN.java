package org.faultTree;

import org.oristool.petrinet.Marking;
import org.oristool.petrinet.PetriNet;

public class GSPN {
    private PetriNet petriNet;
    private Marking marking;

    public GSPN(PetriNet petriNet, Marking marking) {
        this.petriNet = petriNet;
        this.marking = marking;
    }

    public PetriNet getPetriNet() {
        return petriNet;
    }

    public void setPetriNet(PetriNet petriNet) {
        this.petriNet = petriNet;
    }

    public Marking getMarking() {
        return marking;
    }

    public void setMarking(Marking marking) {
        this.marking = marking;
    }
}
