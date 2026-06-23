package org.faultTree.bdd;


import org.faultTree.util.Allocator;
import org.faultTree.util.JDDConsole;
import org.faultTree.util.NodeName;

import java.io.PrintStream;

public class BDDPrinter {
	private static PrintStream ps;
	private static boolean had_0, had_1;

	private static char [] set_chars = null;
	private static int set_chars_len;

	private static void helpGC() { // make thins easier for the garbage collector
		BDDPrinter.ps = null;
	}

	private static final void print_unmark(int bdd, NodeTable nt) { // cleans up the marking
		if(bdd == 0 || bdd == 1) return;
		if(! nt.isNodeMarked(bdd)) return;

		nt.unmark_node(bdd);
		print_unmark( nt.getLow(bdd), nt);
		print_unmark( nt.getHigh(bdd), nt);
	}


	// -----------------------------------------------------
	/** print the part of node-table that describes this BDD */
	public static void print(int bdd, NodeTable nt) {
		JDDConsole.out.printf("\nBDD %d\n", bdd);
		print_rec(bdd, nt);
		print_unmark(bdd, nt);
		helpGC();
	}
	public static void print_rec(int i, NodeTable nt) {
		if(i < 2) return;
		// if( (v[i] & NODE_MARK) != 0) return;
		if( nt.isNodeMarked(i)) return;
		JDDConsole.out.printf("%d\t%d\t%d\t%d\n", i, nt.getVar(i), nt.getLow(i), nt.getHigh(i) );
		nt.mark_node(i);
		print_rec(nt.getLow(i), nt);
		print_rec(nt.getHigh(i), nt);
	}
	// -----------------------------------------------------

	// -----------------------------------------------------------------
	public static void printSet(int bdd, int max, NodeTable nt, NodeName nn)  {
		if( bdd < 2) {
			if(nn == null)
				JDDConsole.out.printf("%s\n", (bdd == 0) ? "FALSE" : "TRUE");
			else
				JDDConsole.out.printf("%s\n", (bdd == 0) ? nn.zero() : nn.one() );
		} else {
			if(BDDPrinter.set_chars == null || BDDPrinter.set_chars.length < max)
				BDDPrinter.set_chars = Allocator.allocateCharArray(max);
			BDDPrinter.set_chars_len = max;

			printSet_rec(bdd, 0, nt, nn);
			JDDConsole.out.printf("\n");
			helpGC();
		}
	}

	// XXX: unsure if this really prints what we want
	private static void printSet_rec(int bdd, int level, NodeTable nt, NodeName nn) {
		if(level == set_chars_len) {
			if(nn == null) {
				for(int i = 0; i < set_chars_len; i++)
					JDDConsole.out.print(set_chars[i]);
			} else {
				for(int i = 0; i < set_chars_len; i++)
					if(set_chars[i] == '1')
						JDDConsole.out.printf("%s ", nn.variable(i));
			}

			JDDConsole.out.printf("\n");
			return;
		}

		int var = nt.getVar(bdd);
		if(var > level || bdd == 1 ) {
			set_chars[level] = '-';
			printSet_rec(bdd, level+1, nt, nn);
			return;
		}

		int low = nt.getLow(bdd);
		int high = nt.getHigh(bdd);

		if(low != 0) {
			set_chars[level] = '0';
			printSet_rec(low, level+1, nt, nn);
		}

		if(high != 0) {
			set_chars[level] = '1';
			printSet_rec(high, level+1, nt, nn);
		}
	}
}
